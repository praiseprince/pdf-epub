from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .parser_options import ParserModel


class PaddleClientError(RuntimeError):
    def __init__(self, message: str, *, error_name: str | None = None):
        super().__init__(message)
        self.error_name = error_name

    @property
    def is_timeout(self) -> bool:
        return self.error_name == "RequestTimeoutError" or "timed out" in str(self).lower()

    @property
    def is_auth_error(self) -> bool:
        return self.error_name == "AuthError" or "authentication" in str(self).lower()


class PaddleClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.helper_path = Path(__file__).parent / "node" / "paddle_client.mjs"

    def parse_document(
        self,
        file_path: Path,
        *,
        model: ParserModel,
        on_status: Callable[[dict[str, Any]], None],
        should_cancel: Callable[[], bool],
        page_count: int | None = None,
        page_ranges: str | None = None,
        submit_timeout_seconds: int | None = None,
        wait_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        if self.settings.local_paddle_mode == "fixture":
            return self.fixture_result(file_path, page_count=page_count)

        if not self.settings.baidu_ai_studio_api_key:
            raise PaddleClientError("BAIDU_AI_STUDIO_API_KEY is not configured.")

        payload: dict[str, Any] = {"filePath": str(file_path), "model": model}
        if page_ranges:
            payload["pageRanges"] = page_ranges

        submitted = self._run("submit", payload, request_timeout_seconds=submit_timeout_seconds)
        job_id = submitted.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise PaddleClientError("PaddleOCR did not return a job id.")

        on_status({"paddle_job_id": job_id, "message": "PaddleOCR accepted the document."})

        started = time.monotonic()
        while True:
            if should_cancel():
                raise PaddleClientError("Job canceled before PaddleOCR finished.")
            if wait_timeout_seconds is not None and _elapsed_seconds(started) > wait_timeout_seconds:
                raise PaddleClientError(
                    f"PaddleOCR did not finish within {wait_timeout_seconds}s.",
                    error_name="PollingTimeoutError",
                )

            status_timeout = self.settings.paddle_status_timeout_seconds
            remaining = _remaining_seconds(started, wait_timeout_seconds)
            if remaining is not None:
                status_timeout = max(1, min(status_timeout, remaining))
            status = self._run("status", {"jobId": job_id}, request_timeout_seconds=status_timeout)
            on_status(status)
            state = status.get("state")
            if state == "done":
                break
            if state == "failed":
                error = status.get("errorMsg") or "PaddleOCR document parsing failed."
                raise PaddleClientError(str(error))
            time.sleep(self.settings.paddle_poll_seconds)

        result_payload: dict[str, Any] = {"jobId": job_id, "model": model}
        if page_ranges:
            result_payload["pageRanges"] = page_ranges
        return self._run("result", result_payload, request_timeout_seconds=self.settings.paddle_status_timeout_seconds)

    def parse_pdf_chunks(
        self,
        chunks: list[Any],
        *,
        model: ParserModel,
        on_chunk_start: Callable[[int, int, Any], None],
        on_status: Callable[[int, Any, dict[str, Any]], None],
        should_cancel: Callable[[], bool],
        submit_timeout_seconds: int,
        wait_timeout_seconds: int,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        if not chunks:
            raise PaddleClientError("No PDF chunks were created for Baidu OCR.")

        stop_event = threading.Event()
        completed: list[tuple[Any, dict[str, Any]]] = []
        chunk_jobs: list[dict[str, Any]] = []
        chunk_retries: list[dict[str, str]] = []
        pending = list(chunks)
        retry_round = 0
        retry_limit = max(0, self.settings.paddle_chunk_retries)
        initial_total = len(chunks)

        def canceled() -> bool:
            return stop_event.is_set() or should_cancel()

        def budget(default: int) -> int:
            if deadline_monotonic is None:
                return max(1, default)
            remaining = int(deadline_monotonic - time.monotonic())
            if remaining <= 0:
                raise PaddleClientError("Baidu PDF chunk OCR exceeded the configured time budget.", error_name="PollingTimeoutError")
            return max(1, min(default, remaining))

        def parse_one(chunk: Any, total: int) -> dict[str, Any]:
            if canceled():
                raise PaddleClientError("Job canceled before PaddleOCR finished.")
            on_chunk_start(chunk.index, total, chunk)
            return self.parse_document(
                chunk.path,
                model=model,
                on_status=lambda status, chunk=chunk: on_status(chunk.index, chunk, status),
                should_cancel=canceled,
                page_count=chunk.page_count,
                submit_timeout_seconds=budget(submit_timeout_seconds),
                wait_timeout_seconds=budget(wait_timeout_seconds),
            )

        while pending:
            total = initial_total if retry_round == 0 else len(pending)
            max_workers = max(1, min(self.settings.paddle_chunk_concurrency, len(pending)))
            failed: list[tuple[Any, PaddleClientError]] = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_by_chunk = {executor.submit(parse_one, chunk, total): chunk for chunk in pending}
                for future in as_completed(future_by_chunk):
                    chunk = future_by_chunk[future]
                    detail = f"PDF chunk {chunk.index} (pages {chunk.label})"
                    try:
                        result = future.result()
                    except PaddleClientError as exc:
                        if exc.is_auth_error or canceled():
                            stop_event.set()
                            for waiting in future_by_chunk:
                                waiting.cancel()
                            raise PaddleClientError(f"{detail} failed: {exc}", error_name=exc.error_name) from exc
                        failed.append((chunk, exc))
                    except Exception as exc:
                        if canceled():
                            stop_event.set()
                            for waiting in future_by_chunk:
                                waiting.cancel()
                            raise PaddleClientError(f"{detail} failed: {exc}") from exc
                        failed.append((chunk, PaddleClientError(str(exc))))
                    else:
                        completed.append((chunk, result))
                        chunk_jobs.append(
                            {
                                "chunk": chunk.index,
                                "pages": chunk.label,
                                "attempt": str(getattr(chunk, "attempt", 1)),
                                "jobId": result.get("jobId"),
                                "source": "pdf_chunk",
                                "variant": getattr(chunk, "variant", "source_pdf"),
                            }
                        )

            if not failed:
                break

            if retry_round >= retry_limit:
                details = "; ".join(f"pages {chunk.label}: {error}" for chunk, error in failed)
                first_error = failed[0][1]
                raise PaddleClientError(
                    f"PDF chunk OCR failed after {retry_round + 1} attempt(s): {details}",
                    error_name=first_error.error_name,
                ) from first_error

            retry_round += 1
            next_pending: list[Any] = []
            for chunk, error in failed:
                retry_chunks = _retry_chunks_for(
                    chunk,
                    attempt=retry_round + 1,
                    target_bytes=self.settings.paddle_chunk_target_bytes,
                    raster_dpi=self.settings.paddle_chunk_retry_raster_dpi,
                )
                next_pending.extend(retry_chunks)
                chunk_retries.append(
                    {
                        "pages": chunk.label,
                        "attempt": str(retry_round + 1),
                        "retryPages": ", ".join(retry_chunk.label for retry_chunk in retry_chunks),
                        "variants": ", ".join(retry_chunk.variant for retry_chunk in retry_chunks),
                        "reason": str(error),
                    }
                )
            pending = next_pending

        pages: list[dict[str, Any]] = []
        for chunk, result in sorted(completed, key=lambda item: (item[0].start_page, item[0].end_page)):
            pages.extend(result.get("pages") or [])

        return {
            "jobId": f"pdf-chunks-{int(time.time())}",
            "pages": pages,
            "dataInfo": {
                "strategy": "pdf_chunks",
                "model": model,
                "chunkJobs": chunk_jobs,
                "chunkRetries": chunk_retries,
            },
        }

    def parse_page_images(
        self,
        page_paths: list[Path],
        *,
        model: ParserModel,
        on_page_start: Callable[[int, int, int], None],
        on_status: Callable[[int, int, dict[str, Any]], None],
        should_cancel: Callable[[], bool],
    ) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        page_jobs: list[dict[str, Any]] = []
        total = len(page_paths)
        retries = max(1, self.settings.paddle_page_submit_retries)

        for index, page_path in enumerate(page_paths, start=1):
            page_error: PaddleClientError | None = None
            for attempt in range(1, retries + 1):
                if should_cancel():
                    raise PaddleClientError("Job canceled before PaddleOCR finished.")
                on_page_start(index, total, attempt)
                try:
                    result = self.parse_document(
                        page_path,
                        model=model,
                        page_count=1,
                        submit_timeout_seconds=self.settings.paddle_page_submit_timeout_seconds,
                        should_cancel=should_cancel,
                        on_status=lambda status, page=index, try_no=attempt: on_status(page, try_no, status),
                    )
                    page_jobs.append(
                        {
                            "page": index,
                            "attempt": attempt,
                            "jobId": result.get("jobId"),
                            "source": "rendered_page",
                        }
                    )
                    pages.extend(result.get("pages") or [])
                    page_error = None
                    break
                except PaddleClientError as exc:
                    page_error = exc
                    if exc.is_auth_error or attempt >= retries:
                        break
                    time.sleep(min(2 * attempt, 8))

            if page_error is not None:
                raise PaddleClientError(
                    f"Page {index} OCR failed after {retries} attempt(s): {page_error}",
                    error_name=page_error.error_name,
                ) from page_error

        return {
            "jobId": f"rendered-pages-{int(time.time())}",
            "pages": pages,
            "dataInfo": {"strategy": "rendered_pages", "model": model, "pageJobs": page_jobs},
        }

    def fixture_result(self, pdf_path: Path, *, page_count: int | None = None) -> dict[str, Any]:
        pages = []
        if page_count is None:
            page_count = 1
        for index in range(page_count):
            pages.append(
                {
                    "markdownText": f"## Page {index + 1}\n\nFixture OCR text for `{pdf_path.name}` page {index + 1}.",
                    "markdownImages": {},
                    "outputImages": {},
                }
            )
        return {"jobId": f"fixture-{pdf_path.stem}", "pages": pages, "dataInfo": {"fixture": True}}

    def _run(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        request_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        env["BAIDU_AI_STUDIO_API_KEY"] = self.settings.baidu_ai_studio_api_key
        env["PADDLEOCR_MODEL"] = str(payload.get("model") or self.settings.paddle_model)
        if request_timeout_seconds:
            env["PADDLEOCR_REQUEST_TIMEOUT_MS"] = str(max(1, request_timeout_seconds) * 1000)
        env["PADDLEOCR_POLL_TIMEOUT_MS"] = "3600000"
        process_timeout = None
        if request_timeout_seconds:
            process_timeout = max(1, request_timeout_seconds) + 30

        try:
            proc = subprocess.run(
                ["node", str(self.helper_path), command],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=process_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaddleClientError(
                f"Paddle helper timed out after {process_timeout}s while running {command}.",
                error_name="RequestTimeoutError",
            ) from exc
        if proc.returncode != 0:
            raise self._helper_error(command, proc.stdout, proc.stderr)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise PaddleClientError("Paddle helper returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise PaddleClientError("Paddle helper returned an unexpected response.")
        return data

    def _helper_error(self, command: str, stdout: str, stderr: str) -> PaddleClientError:
        detail = stderr.strip() or stdout.strip() or f"Paddle helper failed for {command}."
        last_line = detail.splitlines()[-1] if detail else ""
        try:
            parsed = json.loads(last_line)
        except json.JSONDecodeError:
            return PaddleClientError(detail)

        if isinstance(parsed, dict):
            message = str(parsed.get("message") or detail)
            error_name = parsed.get("name")
            return PaddleClientError(message, error_name=str(error_name) if error_name else None)
        return PaddleClientError(detail)


def _elapsed_seconds(started: float) -> float:
    return time.monotonic() - started


def _remaining_seconds(started: float, timeout_seconds: int | None) -> int | None:
    if timeout_seconds is None:
        return None
    return max(1, int(timeout_seconds - _elapsed_seconds(started)))


@dataclass(frozen=True)
class _RetryChunk:
    index: int
    start_page: int
    end_page: int
    path: Path
    attempt: int
    parent_label: str
    variant: str

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def label(self) -> str:
        if self.start_page == self.end_page:
            return str(self.start_page)
        return f"{self.start_page}-{self.end_page}"


def _retry_chunks_for(chunk: Any, *, attempt: int, target_bytes: int, raster_dpi: int) -> list[_RetryChunk]:
    if chunk.page_count <= 1:
        path, variant = _page_retry_path(chunk.path, chunk, attempt=attempt, target_bytes=target_bytes, raster_dpi=raster_dpi)
        return [
            _RetryChunk(
                index=chunk.index * 1000 + attempt,
                start_page=chunk.start_page,
                end_page=chunk.end_page,
                path=path,
                attempt=attempt,
                parent_label=chunk.label,
                variant=variant,
            )
        ]

    try:
        import fitz

        retry_dir = chunk.path.parent / "retry-pages"
        retry_dir.mkdir(parents=True, exist_ok=True)
        retry_chunks: list[_RetryChunk] = []
        with fitz.open(chunk.path) as source:
            for local_index in range(source.page_count):
                original_page = chunk.start_page + local_index
                retry_path = retry_dir / f"retry-{chunk.index:03d}-attempt-{attempt}-page-{original_page:04d}.pdf"
                with fitz.open() as single_page:
                    single_page.insert_pdf(source, from_page=local_index, to_page=local_index)
                    single_page.save(retry_path, garbage=4, deflate=True)
                retry_path, variant = _page_retry_path(
                    retry_path,
                    chunk,
                    attempt=attempt,
                    target_bytes=target_bytes,
                    raster_dpi=raster_dpi,
                    original_page=original_page,
                )
                retry_chunks.append(
                    _RetryChunk(
                        index=chunk.index * 1000 + original_page,
                        start_page=original_page,
                        end_page=original_page,
                        path=retry_path,
                        attempt=attempt,
                        parent_label=chunk.label,
                        variant=variant,
                    )
                )
        return retry_chunks
    except Exception as exc:
        raise PaddleClientError(f"Could not prepare retry pages for PDF chunk {chunk.label}: {exc}") from exc


def _page_retry_path(
    page_pdf_path: Path,
    chunk: Any,
    *,
    attempt: int,
    target_bytes: int,
    raster_dpi: int,
    original_page: int | None = None,
) -> tuple[Path, str]:
    if raster_dpi <= 0:
        return page_pdf_path, "source_pdf"
    if target_bytes > 0 and page_pdf_path.stat().st_size <= target_bytes:
        return page_pdf_path, "source_pdf"

    page_number = original_page or chunk.start_page
    retry_dir = page_pdf_path.parent / "rasterized"
    retry_dir.mkdir(parents=True, exist_ok=True)
    rasterized_path = retry_dir / f"retry-{chunk.index:03d}-attempt-{attempt}-page-{page_number:04d}-raster.pdf"
    _rasterize_single_page_pdf(page_pdf_path, rasterized_path, dpi=raster_dpi)
    if rasterized_path.stat().st_size >= page_pdf_path.stat().st_size:
        return page_pdf_path, "source_pdf"
    return rasterized_path, "rasterized_pdf"


def _rasterize_single_page_pdf(pdf_path: Path, output_path: Path, *, dpi: int) -> None:
    import fitz
    from PIL import Image

    scale = max(36, dpi) / 72
    with fitz.open(pdf_path) as source:
        if source.page_count != 1:
            raise PaddleClientError(f"Expected one page in retry PDF, found {source.page_count}.")
        source_page = source[0]
        rect = source_page.rect
        pixmap = source_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        image_stream = BytesIO()
        image.save(image_stream, format="JPEG", quality=88, optimize=True)

        with fitz.open() as target:
            page = target.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=image_stream.getvalue())
            target.save(output_path, garbage=4, deflate=True)
