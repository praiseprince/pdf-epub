from __future__ import annotations

import json
import os
import subprocess
import time
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
        submit_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        if self.settings.local_paddle_mode == "fixture":
            return self.fixture_result(file_path, page_count=page_count)

        if not self.settings.paddleocr_access_token:
            raise PaddleClientError("PADDLEOCR_ACCESS_TOKEN is not configured.")

        submitted = self._run(
            "submit",
            {"filePath": str(file_path), "model": model},
            request_timeout_seconds=submit_timeout_seconds,
        )
        job_id = submitted.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise PaddleClientError("PaddleOCR did not return a job id.")

        on_status({"paddle_job_id": job_id, "message": "PaddleOCR accepted the document."})

        while True:
            if should_cancel():
                raise PaddleClientError("Job canceled before PaddleOCR finished.")

            status = self._run("status", {"jobId": job_id})
            on_status(status)
            state = status.get("state")
            if state == "done":
                break
            if state == "failed":
                error = status.get("errorMsg") or "PaddleOCR document parsing failed."
                raise PaddleClientError(str(error))
            time.sleep(self.settings.paddle_poll_seconds)

        return self._run("result", {"jobId": job_id, "model": model})

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
        env["PADDLEOCR_ACCESS_TOKEN"] = self.settings.paddleocr_access_token
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
