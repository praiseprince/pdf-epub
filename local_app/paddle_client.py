from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import Settings


class PaddleClientError(RuntimeError):
    pass


class PaddleClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.helper_path = Path(__file__).parent / "node" / "paddle_client.mjs"

    def parse_document(
        self,
        pdf_path: Path,
        *,
        on_status: Callable[[dict[str, Any]], None],
        should_cancel: Callable[[], bool],
        page_count: int | None = None,
    ) -> dict[str, Any]:
        if self.settings.local_paddle_mode == "fixture":
            return self.fixture_result(pdf_path, page_count=page_count)

        if not self.settings.paddleocr_access_token:
            raise PaddleClientError("PADDLEOCR_ACCESS_TOKEN is not configured.")

        submitted = self._run("submit", {"filePath": str(pdf_path)})
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

        return self._run("result", {"jobId": job_id})

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

    def _run(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        env = os.environ.copy()
        env["PADDLEOCR_ACCESS_TOKEN"] = self.settings.paddleocr_access_token
        proc = subprocess.run(
            ["node", str(self.helper_path), command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"Paddle helper failed for {command}."
            raise PaddleClientError(detail)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise PaddleClientError("Paddle helper returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise PaddleClientError("Paddle helper returned an unexpected response.")
        return data
