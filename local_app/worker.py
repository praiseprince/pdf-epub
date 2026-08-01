from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from .assets import add_page_snapshots, collect_paddle_assets, merge_bundles
from .config import Settings
from .database import JobRecord, JobStore, utc_now
from .epub_builder import build_epub, write_raw_result
from .paths import job_dirs, job_epub_dir, job_ocr_dir, job_pages_dir
from .paddle_client import PaddleClient, PaddleClientError
from .pdf_tools import PdfToolError, pdfinfo, render_pdf_pages


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

        snapshot_paths: list[Path] = []
        raw_result: dict[str, Any] | None = None
        raw_result_path: Path | None = None
        parse_error: str | None = None

        try:
            source_path = Path(job.source_path)
            self._check_cancel(job_id)
            info = pdfinfo(source_path)
            pages = int(info.get("pages", 0) or 0)
            self.store.update_job(job_id, pages=pages)

            if source_path.stat().st_size > self.settings.max_pdf_size_bytes:
                raise RuntimeError(f"PDF exceeds {self.settings.max_pdf_size_mb} MB, the configured Baidu guardrail.")
            if pages > self.settings.max_pdf_pages:
                raise RuntimeError(f"PDF has {pages} pages; configured Baidu guardrail is {self.settings.max_pdf_pages}.")

            if job.include_snapshots and self.settings.include_page_snapshots:
                self.store.update_job(
                    job_id,
                    stage="Rendering page images",
                    message="Rendering original PDF pages as the visual safety layer.",
                    progress_total=pages,
                )
                pages_dir = job_pages_dir(self.settings, job_id)
                shutil.rmtree(pages_dir, ignore_errors=True)
                snapshot_paths = render_pdf_pages(source_path, pages_dir, dpi=self.settings.snapshot_dpi)
                self.store.update_job(job_id, progress_done=len(snapshot_paths))

            self._check_cancel(job_id)
            self.store.update_job(
                job_id,
                stage="Sending to document parser",
                message="Submitting the local PDF file to Baidu PaddleOCR.",
                progress_done=0,
                progress_total=pages,
            )

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
                raw_result = client.parse_document(
                    source_path,
                    on_status=on_paddle_status,
                    should_cancel=lambda: self._cancel_requested(job_id),
                    page_count=pages,
                )
                raw_result_path = job_ocr_dir(self.settings, job_id) / "raw-result.json"
                write_raw_result(raw_result_path, raw_result)
                self.store.update_job(job_id, raw_result_path=raw_result_path)
            except PaddleClientError as exc:
                parse_error = str(exc)
                if not snapshot_paths:
                    raise RuntimeError(parse_error) from exc

            self._check_cancel(job_id)
            message = "Building EPUB from OCR text and page images."
            if parse_error:
                message = "OCR failed, so building a visual fallback EPUB from PDF page images."
            self.store.update_job(job_id, stage="Building EPUB", message=message)

            ocr_assets_dir = job_ocr_dir(self.settings, job_id) / "assets"
            ocr_bundle = collect_paddle_assets(
                raw_result,
                ocr_assets_dir,
                max_image_bytes=self.settings.max_image_size_bytes,
                max_total_bytes=self.settings.max_total_asset_bytes,
            )
            page_bundle = add_page_snapshots(snapshot_paths)
            bundle = merge_bundles(ocr_bundle, page_bundle)
            if parse_error:
                bundle.warnings.append(f"PaddleOCR failed: {parse_error}")

            output_path = job_epub_dir(self.settings, job_id) / f"{Path(job.source_filename).stem}.epub"
            build_result = build_epub(
                output_path=output_path,
                title=job.title,
                author=job.author,
                original_filename=job.source_filename,
                raw_result=raw_result,
                bundle=bundle,
                snapshot_paths=snapshot_paths,
                snapshot_source_dir=job_pages_dir(self.settings, job_id),
                assets_source_dir=ocr_assets_dir,
            )

            final_message = "EPUB is ready."
            if parse_error:
                final_message = "EPUB is ready using visual fallback pages because OCR failed."
            elif build_result.warnings:
                final_message = f"EPUB is ready with {len(build_result.warnings)} conversion note(s)."

            self.store.update_job(
                job_id,
                status="done",
                stage="Ready to download",
                message=final_message,
                epub_path=build_result.output_path,
                error=parse_error,
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


def delete_job_files(settings: Settings, job_id: str) -> None:
    for path in job_dirs(settings, job_id):
        shutil.rmtree(path, ignore_errors=True)
