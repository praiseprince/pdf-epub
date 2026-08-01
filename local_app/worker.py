from __future__ import annotations

import asyncio
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .assets import add_page_snapshots, collect_paddle_assets, merge_bundles
from .comic_converter import KccComicConverter, KccComicError
from .config import Settings
from .conversion_options import (
    normalize_comic_layout,
    normalize_comic_output_format,
    normalize_conversion_mode,
)
from .database import JobRecord, JobStore, utc_now
from .epub_builder import build_epub, figure_crop_page_numbers, write_raw_result
from .parser_options import ParserModel, normalize_parser_model, normalize_parser_strategy
from .paths import job_dirs, job_epub_dir, job_ocr_dir, job_pages_dir
from .paddle_client import PaddleClient, PaddleClientError
from .pdf_tools import pdfinfo, render_pdf_pages, split_pdf_chunks


class JobCanceled(RuntimeError):
    pass


class JobWorker:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings = settings
        self.store = store
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.running = False

    async def start(self) -> None:
        self.running = True
        for job in self.store.jobs_to_resume():
            if job.status == "running":
                self.store.update_job(
                    job.id,
                    status="queued",
                    stage="Queued",
                    message="Recovered after app restart. Waiting for the local worker.",
                )
            await self.queue.put(job.id)
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def _loop(self) -> None:
        while self.running:
            job_id = await self.queue.get()
            try:
                await asyncio.to_thread(self._process_job, job_id)
            finally:
                self.queue.task_done()

    def _process_job(self, job_id: str) -> None:
        job = self.store.maybe_get_job(job_id)
        if job is None or job.status not in {"queued", "running"}:
            return

        self.store.update_job(
            job_id,
            status="running",
            stage="Inspecting PDF",
            message="Checking size, page count, and local files.",
            started_at=job.started_at or utc_now(),
            finished_at=None,
            error=None,
            progress_done=0,
            progress_total=0,
        )

        cover_snapshot_paths: list[Path] = []
        raw_result: dict[str, Any] | None = None
        raw_result_path: Path | None = None
        ocr_notes: list[str] = []

        try:
            source_path = Path(job.source_path)
            parser_model = normalize_parser_model(job.parser_model)
            parser_strategy = normalize_parser_strategy(job.parser_strategy)
            self._check_cancel(job_id)
            info = pdfinfo(source_path)
            pages = int(info.get("pages", 0) or 0)
            self.store.update_job(job_id, pages=pages)

            conversion_mode = normalize_conversion_mode(job.conversion_mode)
            if conversion_mode == "comic":
                self._process_comic_job(job, source_path, pages=pages)
                return

            if source_path.stat().st_size > self.settings.max_pdf_size_bytes:
                raise RuntimeError(f"PDF exceeds {self.settings.max_pdf_size_mb} MB, the configured Baidu guardrail.")
            if pages > self.settings.max_pdf_pages:
                raise RuntimeError(f"PDF has {pages} pages; configured Baidu guardrail is {self.settings.max_pdf_pages}.")

            if job.include_snapshots and self.settings.include_page_snapshots:
                self.store.update_job(
                    job_id,
                    stage="Rendering page images",
                    message="Rendering the first PDF page as the EPUB cover.",
                    progress_total=1,
                )
                pages_dir = job_pages_dir(self.settings, job_id)
                shutil.rmtree(pages_dir, ignore_errors=True)
                snapshot_paths = render_pdf_pages(
                    source_path,
                    pages_dir,
                    dpi=self.settings.snapshot_dpi,
                    first_page=1,
                    last_page=1,
                )
                cover_snapshot_paths = snapshot_paths
                self.store.update_job(job_id, progress_done=len(cover_snapshot_paths))

            self._check_cancel(job_id)
            client = PaddleClient(self.settings)

            def on_paddle_status(status: dict[str, Any]) -> None:
                update: dict[str, Any] = {"stage": "Reading document"}
                if status.get("paddle_job_id"):
                    update["paddle_job_id"] = status["paddle_job_id"]
                if status.get("jobId"):
                    update["paddle_job_id"] = status["jobId"]
                progress = status.get("progress")
                if isinstance(progress, dict):
                    update["progress_done"] = int(progress.get("extractedPages") or 0)
                    update["progress_total"] = int(progress.get("totalPages") or pages)
                    update["message"] = "PaddleOCR is reading the document."
                elif status.get("message"):
                    update["message"] = str(status["message"])
                self.store.update_job(job_id, **update)

            try:
                raw_result = self._parse_with_baidu(
                    job,
                    source_path,
                    pages=pages,
                    parser_model=parser_model,
                    parser_strategy=parser_strategy,
                    client=client,
                    on_full_status=on_paddle_status,
                    ocr_notes=ocr_notes,
                )
                if not raw_result.get("pages"):
                    raise RuntimeError("PaddleOCR returned no pages.")
                raw_result_path = job_ocr_dir(self.settings, job_id) / "raw-result.json"
                write_raw_result(raw_result_path, raw_result)
                self.store.update_job(job_id, raw_result_path=raw_result_path)
            except PaddleClientError as exc:
                raise RuntimeError(f"PaddleOCR failed after retries: {exc}") from exc

            self._check_cancel(job_id)
            self._render_figure_crop_pages(job_id, source_path, raw_result)
            self._check_cancel(job_id)
            message = "Building EPUB from OCR text, figures, and rendered formulas."
            self.store.update_job(job_id, stage="Building EPUB", message=message)

            ocr_assets_dir = job_ocr_dir(self.settings, job_id) / "assets"
            ocr_bundle = collect_paddle_assets(
                raw_result,
                ocr_assets_dir,
                max_image_bytes=self.settings.max_image_size_bytes,
                max_total_bytes=self.settings.max_total_asset_bytes,
            )
            build_snapshot_paths = cover_snapshot_paths
            page_bundle = add_page_snapshots(build_snapshot_paths)
            base_bundle = merge_bundles(ocr_bundle, page_bundle)
            base_bundle.warnings.extend(ocr_notes)

            output_path = job_epub_dir(self.settings, job_id) / f"{Path(job.source_filename).stem}.epub"
            build_result = build_epub(
                output_path=output_path,
                title=job.title,
                author=job.author,
                original_filename=job.source_filename,
                raw_result=raw_result,
                bundle=merge_bundles(base_bundle),
                snapshot_paths=build_snapshot_paths,
                snapshot_source_dir=job_pages_dir(self.settings, job_id),
                assets_source_dir=ocr_assets_dir,
            )
            if job.create_kepub:
                kepub_path = output_path.with_name(f"{output_path.stem}.kepub.epub")
                kepub_result = build_epub(
                    output_path=kepub_path,
                    title=job.title,
                    author=job.author,
                    original_filename=job.source_filename,
                    raw_result=raw_result,
                    bundle=merge_bundles(base_bundle),
                    snapshot_paths=build_snapshot_paths,
                    snapshot_source_dir=job_pages_dir(self.settings, job_id),
                    assets_source_dir=ocr_assets_dir,
                )
                build_result.warnings.extend(kepub_result.warnings)

            final_message = "EPUB is ready."
            if ocr_notes:
                final_message = f"EPUB is ready with {len(ocr_notes)} conversion note(s)."
            elif build_result.warnings:
                final_message = f"EPUB is ready with {len(build_result.warnings)} conversion note(s)."

            self.store.update_job(
                job_id,
                status="done",
                stage="Ready to download",
                message=final_message,
                epub_path=build_result.output_path,
                error=None,
                progress_done=pages,
                progress_total=pages,
                finished_at=utc_now(),
            )
        except JobCanceled:
            if self.store.maybe_get_job(job_id):
                self.store.update_job(
                    job_id,
                    status="canceled",
                    stage="Canceled",
                    message="Conversion was canceled.",
                    finished_at=utc_now(),
                )
        except Exception as exc:
            if self.store.maybe_get_job(job_id):
                self.store.update_job(
                    job_id,
                    status="failed",
                    stage="Failed",
                    message="Conversion failed.",
                    error=str(exc),
                    finished_at=utc_now(),
                )

    def _cancel_requested(self, job_id: str) -> bool:
        job = self.store.maybe_get_job(job_id)
        return job is None or job.cancel_requested

    def _check_cancel(self, job_id: str) -> None:
        if self._cancel_requested(job_id):
            raise JobCanceled()

    def _parse_with_baidu(
        self,
        job: JobRecord,
        source_path: Path,
        *,
        pages: int,
        parser_model: ParserModel,
        parser_strategy: str,
        client: PaddleClient,
        on_full_status: Any,
        ocr_notes: list[str],
    ) -> dict[str, Any]:
        if self.settings.local_paddle_mode == "local":
            ocr_notes.append("OCR used local PaddleOCR-VL page-by-page checkpoints.")
            return self._parse_rendered_pages(job, source_path, pages=pages, parser_model=parser_model, client=client)

        auto_deadline = None
        if parser_strategy == "auto":
            auto_deadline = time.monotonic() + max(1, self.settings.paddle_auto_ocr_timeout_seconds)

        def timeout_budget(default: int) -> int:
            if auto_deadline is None:
                return max(1, default)
            remaining = int(auto_deadline - time.monotonic())
            if remaining <= 0:
                raise PaddleClientError(
                    f"Auto OCR exceeded {self.settings.paddle_auto_ocr_timeout_seconds}s before Baidu finished.",
                    error_name="PollingTimeoutError",
                )
            return max(1, min(default, remaining))

        if parser_strategy == "pdf_chunks" or (
            parser_strategy == "auto" and self._should_start_with_pdf_chunks(source_path, pages)
        ):
            if parser_strategy == "auto":
                ocr_notes.append(
                    "Auto OCR used PDF chunks immediately because the file looks image-heavy enough "
                    "to make full-PDF submission unreliable."
                )
            return self._parse_pdf_chunks(
                job,
                source_path,
                pages=pages,
                parser_model=parser_model,
                client=client,
                submit_timeout_seconds=timeout_budget(self.settings.paddle_submit_timeout_seconds),
                wait_timeout_seconds=timeout_budget(self.settings.paddle_chunk_timeout_seconds),
                deadline_monotonic=auto_deadline,
            )

        if parser_strategy in {"auto", "full_document"}:
            submit_timeout = self.settings.paddle_submit_timeout_seconds
            wait_timeout = self.settings.paddle_auto_ocr_timeout_seconds if parser_strategy == "auto" else None
            if parser_strategy == "auto":
                submit_timeout = timeout_budget(submit_timeout)
                wait_timeout = timeout_budget(wait_timeout)
            self.store.update_job(
                job.id,
                stage="Submitting document",
                message=(
                    "Uploading the full PDF to Baidu PaddleOCR. "
                    f"If Baidu does not accept or finish it within {submit_timeout}s, "
                    "the worker can switch to PDF chunks."
                ),
                progress_done=0,
                progress_total=pages,
            )
            try:
                return client.parse_document(
                    source_path,
                    model=parser_model,
                    on_status=on_full_status,
                    should_cancel=lambda: self._cancel_requested(job.id),
                    page_count=pages,
                    submit_timeout_seconds=submit_timeout,
                    wait_timeout_seconds=wait_timeout,
                )
            except PaddleClientError as exc:
                if parser_strategy == "full_document" or exc.is_auth_error:
                    raise
                note = f"Full PDF parsing did not finish, so OCR used PDF chunks instead: {exc}"
                ocr_notes.append(note)
                if auto_deadline is not None and time.monotonic() >= auto_deadline:
                    raise PaddleClientError(
                        f"Auto OCR reached {self.settings.paddle_auto_ocr_timeout_seconds}s before chunk fallback could start: {exc}",
                        error_name=exc.error_name,
                    ) from exc
                return self._parse_pdf_chunks(
                    job,
                    source_path,
                    pages=pages,
                    parser_model=parser_model,
                    client=client,
                    submit_timeout_seconds=timeout_budget(self.settings.paddle_submit_timeout_seconds),
                    wait_timeout_seconds=timeout_budget(self.settings.paddle_chunk_timeout_seconds),
                    deadline_monotonic=auto_deadline,
                )

        return self._parse_rendered_pages(job, source_path, pages=pages, parser_model=parser_model, client=client)

    def _parse_pdf_chunks(
        self,
        job: JobRecord,
        source_path: Path,
        *,
        pages: int,
        parser_model: ParserModel,
        client: PaddleClient,
        submit_timeout_seconds: int,
        wait_timeout_seconds: int,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        self._check_cancel(job.id)
        self.store.update_job(
            job.id,
            stage="Preparing PDF chunks",
            message=(
                f"Splitting the PDF into chunks of up to {self.settings.paddle_chunk_pages} pages "
                f"or about {self.settings.paddle_chunk_target_mb} MB for Baidu OCR."
            ),
            progress_done=0,
            progress_total=pages,
        )
        chunk_dir = job_ocr_dir(self.settings, job.id) / "pdf-chunks"
        shutil.rmtree(chunk_dir, ignore_errors=True)
        chunks = split_pdf_chunks(
            source_path,
            chunk_dir,
            chunk_pages=self.settings.paddle_chunk_pages,
            target_bytes=self.settings.paddle_chunk_target_bytes,
        )
        if not chunks:
            raise PaddleClientError("No PDF chunks were created for Baidu OCR.")

        progress_by_chunk: dict[int, int] = {chunk.index: 0 for chunk in chunks}
        lock = threading.Lock()

        def total_progress() -> int:
            return min(pages, sum(progress_by_chunk.values()))

        def chunk_message(chunk_index: int, total_chunks: int, chunk: Any, verb: str) -> str:
            attempt = int(getattr(chunk, "attempt", 1) or 1)
            if attempt > 1:
                parent_label = str(getattr(chunk, "parent_label", chunk.label))
                variant = str(getattr(chunk, "variant", "source_pdf"))
                kind = "rasterized retry" if variant == "rasterized_pdf" else "retry"
                return f"{verb} {kind} for PDF pages {chunk.label} from chunk pages {parent_label}."
            return f"{verb} PDF chunk {chunk_index} of {total_chunks} (pages {chunk.label})."

        def on_chunk_start(chunk_index: int, total_chunks: int, chunk: Any) -> None:
            with lock:
                done = total_progress()
            self.store.update_job(
                job.id,
                stage="Submitting PDF chunks",
                message=chunk_message(chunk_index, total_chunks, chunk, "Uploading"),
                progress_done=done,
                progress_total=pages,
            )

        def on_chunk_status(chunk_index: int, chunk: Any, status: dict[str, Any]) -> None:
            update: dict[str, Any] = {
                "stage": "Reading PDF chunks",
                "message": chunk_message(chunk_index, len(chunks), chunk, "Baidu is reading"),
                "progress_total": pages,
            }
            if status.get("paddle_job_id"):
                update["paddle_job_id"] = status["paddle_job_id"]
            if status.get("jobId"):
                update["paddle_job_id"] = status["jobId"]

            progress = status.get("progress")
            with lock:
                if isinstance(progress, dict):
                    extracted = int(progress.get("extractedPages") or 0)
                    progress_by_chunk[chunk_index] = min(chunk.page_count, max(0, extracted))
                elif status.get("state") == "done":
                    progress_by_chunk[chunk_index] = chunk.page_count
                update["progress_done"] = total_progress()

            if status.get("message"):
                update["message"] = status["message"]
            self.store.update_job(job.id, **update)

        result = client.parse_pdf_chunks(
            chunks,
            model=parser_model,
            on_chunk_start=on_chunk_start,
            on_status=on_chunk_status,
            should_cancel=lambda: self._cancel_requested(job.id),
            submit_timeout_seconds=submit_timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            deadline_monotonic=deadline_monotonic,
        )
        self.store.update_job(
            job.id,
            stage="Reading PDF chunks",
            message="Baidu PDF chunk OCR finished.",
            progress_done=pages,
            progress_total=pages,
        )
        return result

    def _should_start_with_pdf_chunks(self, source_path: Path, pages: int) -> bool:
        if pages <= 0:
            return False
        bytes_per_page = source_path.stat().st_size / pages
        return (
            pages >= self.settings.paddle_auto_chunk_min_pages
            and bytes_per_page >= self.settings.paddle_auto_chunk_min_bytes_per_page
        )

    def _parse_rendered_pages(
        self,
        job: JobRecord,
        source_path: Path,
        *,
        pages: int,
        parser_model: ParserModel,
        client: PaddleClient,
    ) -> dict[str, Any]:
        self._check_cancel(job.id)
        self.store.update_job(
            job.id,
            stage="Rendering OCR pages",
            message="Rendering pages locally for page-by-page PaddleOCR.",
            progress_done=0,
            progress_total=pages,
        )
        rendered_dir = job_ocr_dir(self.settings, job.id) / "rendered-pages"
        shutil.rmtree(rendered_dir, ignore_errors=True)
        ocr_dpi = self.settings.local_ocr_dpi if self.settings.local_paddle_mode == "local" else self.settings.snapshot_dpi
        page_paths = render_pdf_pages(source_path, rendered_dir, dpi=ocr_dpi)
        if len(page_paths) != pages:
            raise PaddleClientError(f"Rendered {len(page_paths)} page image(s), expected {pages}.")

        def on_page_start(page: int, total: int, attempt: int) -> None:
            suffix = f" attempt {attempt}" if attempt > 1 else ""
            if self.settings.local_paddle_mode == "local":
                message = f"Running local PaddleOCR on page {page} of {total}{suffix}."
            else:
                message = f"Uploading rendered page {page} of {total} to Baidu{suffix}."
            self.store.update_job(
                job.id,
                stage="Submitting page OCR",
                message=message,
                progress_done=page - 1,
                progress_total=total,
            )

        def on_page_status(page: int, attempt: int, status: dict[str, Any]) -> None:
            update: dict[str, Any] = {
                "stage": "Reading page OCR",
                "message": f"PaddleOCR is reading page {page} of {pages}.",
                "progress_done": page - 1,
                "progress_total": pages,
            }
            if status.get("paddle_job_id"):
                update["paddle_job_id"] = status["paddle_job_id"]
            if status.get("jobId"):
                update["paddle_job_id"] = status["jobId"]
            progress = status.get("progress")
            if isinstance(progress, dict):
                page_done = int(progress.get("extractedPages") or 0)
                update["progress_done"] = min(pages, page - 1 + page_done)
            elif status.get("message"):
                update["message"] = f"Page {page} of {pages}: {status['message']}"
            if attempt > 1:
                update["message"] = f"{update['message']} Retry {attempt}."
            self.store.update_job(job.id, **update)

        result = client.parse_page_images(
            page_paths,
            model=parser_model,
            on_page_start=on_page_start,
            on_status=on_page_status,
            should_cancel=lambda: self._cancel_requested(job.id),
            checkpoint_dir=job_ocr_dir(self.settings, job.id) / "local-page-checkpoints",
        )
        self.store.update_job(
            job.id,
            stage="Reading page OCR",
            message="PaddleOCR page OCR finished.",
            progress_done=pages,
            progress_total=pages,
        )
        return result

    def _render_figure_crop_pages(self, job_id: str, source_path: Path, raw_result: dict[str, Any]) -> None:
        figure_pages = sorted(figure_crop_page_numbers(raw_result))
        if not figure_pages:
            return

        pages_dir = job_pages_dir(self.settings, job_id)
        self.store.update_job(
            job_id,
            stage="Rendering figure crops",
            message=f"Rendering source PDF pages with diagrams or charts at {self.settings.figure_crop_dpi} DPI.",
            progress_done=0,
            progress_total=len(figure_pages),
        )
        for done, page_number in enumerate(figure_pages, start=1):
            self._check_cancel(job_id)
            render_pdf_pages(
                source_path,
                pages_dir,
                dpi=self.settings.figure_crop_dpi,
                first_page=page_number,
                last_page=page_number,
            )
            self.store.update_job(job_id, progress_done=done)

    def _process_comic_job(self, job: JobRecord, source_path: Path, *, pages: int) -> None:
        output_format = normalize_comic_output_format(job.comic_output_format)
        layout = normalize_comic_layout(job.comic_layout)
        rendered_dir = job_pages_dir(self.settings, job.id) / "comic-rendered"
        output_dir = job_epub_dir(self.settings, job.id)
        shutil.rmtree(rendered_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

        self.store.update_job(
            job.id,
            stage="Rendering comic pages",
            message=f"Rendering PDF pages locally at Kobo Clara Colour width ({self.settings.kcc_render_width}px).",
            progress_done=0,
            progress_total=pages,
        )
        page_paths = render_pdf_pages(source_path, rendered_dir, scale_to_width=self.settings.kcc_render_width)
        if not page_paths:
            raise RuntimeError("No comic pages were rendered from the PDF.")

        self._check_cancel(job.id)
        self.store.update_job(
            job.id,
            stage="Running KCC",
            message=f"Optimizing {len(page_paths)} rendered page(s) with Kindle Comic Converter.",
            progress_done=len(page_paths),
            progress_total=len(page_paths),
        )
        converter = KccComicConverter(
            command=self.settings.kcc_c2e_command,
            source_dir=self.settings.kcc_source_dir,
            profile=self.settings.kcc_profile,
            force_color=self.settings.kcc_force_color,
            disable_rotate=self.settings.kcc_disable_rotate,
        )
        try:
            result = converter.convert(
                input_dir=rendered_dir,
                output_dir=output_dir,
                title=job.title,
                author=job.author,
                output_format=output_format,
                layout=layout,
                final_stem=Path(job.source_filename).stem,
            )
        except KccComicError as exc:
            raise RuntimeError(f"KCC conversion failed: {exc}") from exc

        self._check_cancel(job.id)
        self.store.update_job(
            job.id,
            status="done",
            stage="Ready to download",
            message=f"{output_format.upper()} comic output is ready.",
            epub_path=result.output_path,
            error=None,
            progress_done=len(page_paths),
            progress_total=len(page_paths),
            finished_at=utc_now(),
        )


def delete_job_files(settings: Settings, job_id: str) -> None:
    for path in job_dirs(settings, job_id):
        shutil.rmtree(path, ignore_errors=True)
