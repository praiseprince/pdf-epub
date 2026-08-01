from __future__ import annotations

import asyncio
import shutil
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
from .epub_builder import build_epub, write_raw_result
from .llm_repair import MathRepairClient
from .parser_options import ParserModel, normalize_parser_model, normalize_parser_strategy
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
                    raise RuntimeError("Baidu OCR returned no pages.")
                raw_result_path = job_ocr_dir(self.settings, job_id) / "raw-result.json"
                write_raw_result(raw_result_path, raw_result)
                self.store.update_job(job_id, raw_result_path=raw_result_path)
            except PaddleClientError as exc:
                raise RuntimeError(f"Baidu OCR failed after retries: {exc}") from exc

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
                math_repairer=MathRepairClient(self.settings, job.math_repair_provider),
                math_output="png",
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
                    math_repairer=MathRepairClient(self.settings, job.math_repair_provider),
                    math_output="mathml",
                )
                build_result.warnings.extend(kepub_result.warnings)

            final_message = "EPUB is ready."
            if ocr_notes:
                final_message = f"EPUB is ready with {len(ocr_notes)} Baidu retry note(s)."
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
        if parser_strategy in {"auto", "full_document"}:
            self.store.update_job(
                job.id,
                stage="Submitting document",
                message=(
                    "Uploading the full PDF to Baidu PaddleOCR. "
                    f"If Baidu does not accept it within {self.settings.paddle_submit_timeout_seconds}s, "
                    "the worker can switch to page OCR."
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
                    submit_timeout_seconds=self.settings.paddle_submit_timeout_seconds,
                )
            except PaddleClientError as exc:
                if parser_strategy == "full_document" or exc.is_auth_error:
                    raise
                note = f"Full PDF submit failed, so OCR used rendered pages instead: {exc}"
                ocr_notes.append(note)

        return self._parse_rendered_pages(job, source_path, pages=pages, parser_model=parser_model, client=client)

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
            message="Rendering pages locally for page-by-page Baidu OCR.",
            progress_done=0,
            progress_total=pages,
        )
        rendered_dir = job_ocr_dir(self.settings, job.id) / "rendered-pages"
        shutil.rmtree(rendered_dir, ignore_errors=True)
        page_paths = render_pdf_pages(source_path, rendered_dir, dpi=self.settings.snapshot_dpi)
        if len(page_paths) != pages:
            raise PaddleClientError(f"Rendered {len(page_paths)} page image(s), expected {pages}.")

        def on_page_start(page: int, total: int, attempt: int) -> None:
            suffix = f" attempt {attempt}" if attempt > 1 else ""
            self.store.update_job(
                job.id,
                stage="Submitting page OCR",
                message=f"Uploading rendered page {page} of {total} to Baidu{suffix}.",
                progress_done=page - 1,
                progress_total=total,
            )

        def on_page_status(page: int, attempt: int, status: dict[str, Any]) -> None:
            update: dict[str, Any] = {
                "stage": "Reading page OCR",
                "message": f"Baidu is reading page {page} of {pages}.",
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
        )
        self.store.update_job(
            job.id,
            stage="Reading page OCR",
            message="Baidu page OCR finished.",
            progress_done=pages,
            progress_total=pages,
        )
        return result

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
