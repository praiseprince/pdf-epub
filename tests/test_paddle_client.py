from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest
from PIL import Image

from local_app.config import Settings
from local_app.paddle_client import PaddleClient, PaddleClientError, _retry_chunks_for
from local_app.pdf_tools import split_pdf_chunks


class RetryingPaddleClient(PaddleClient):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.calls: list[Path] = []
        self.failures_by_name: dict[str, int] = {}

    def parse_document(
        self,
        file_path: Path,
        *,
        page_count: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(file_path)
        remaining_failures = self.failures_by_name.get(file_path.name, 0)
        if remaining_failures:
            self.failures_by_name[file_path.name] = remaining_failures - 1
            raise PaddleClientError("simulated slow chunk", error_name="PollingTimeoutError")
        return {
            "jobId": f"job-{file_path.stem}",
            "pages": [
                {"markdownText": f"{file_path.name} page {index + 1}", "markdownImages": {}, "outputImages": {}}
                for index in range(page_count or 1)
            ],
        }


def test_pdf_chunk_retry_splits_failed_chunk_into_page_resubmits(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for page_number in range(4):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"Page {page_number + 1}")
        doc.save(source)

    chunks = split_pdf_chunks(source, tmp_path / "chunks", chunk_pages=2)
    settings = Settings(
        LOCAL_PADDLE_CHUNK_CONCURRENCY=2,
        LOCAL_PADDLE_CHUNK_RETRIES=1,
        BAIDU_AI_STUDIO_API_KEY="test",
    )
    client = RetryingPaddleClient(settings)
    client.failures_by_name[chunks[0].path.name] = 1

    result = client.parse_pdf_chunks(
        chunks,
        model="PaddleOCR-VL-1.6",
        on_chunk_start=lambda *_args: None,
        on_status=lambda *_args: None,
        should_cancel=lambda: False,
        submit_timeout_seconds=10,
        wait_timeout_seconds=10,
    )

    assert len(result["pages"]) == 4
    assert result["dataInfo"]["chunkRetries"] == [
        {
            "pages": "1-2",
            "attempt": "2",
            "retryPages": "1, 2",
            "variants": "source_pdf, source_pdf",
            "reason": "simulated slow chunk",
        }
    ]
    assert any(path.name == "retry-001-attempt-2-page-0001.pdf" for path in client.calls)
    assert any(path.name == "retry-001-attempt-2-page-0002.pdf" for path in client.calls)
    assert "local_text_fallback" not in str(result)


def test_pdf_chunk_retry_fails_after_configured_resubmit_rounds(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), "Page 1")
        doc.save(source)

    chunks = split_pdf_chunks(source, tmp_path / "chunks", chunk_pages=1)
    settings = Settings(
        LOCAL_PADDLE_CHUNK_CONCURRENCY=1,
        LOCAL_PADDLE_CHUNK_RETRIES=1,
        BAIDU_AI_STUDIO_API_KEY="test",
    )
    client = RetryingPaddleClient(settings)
    client.failures_by_name[chunks[0].path.name] = 2

    with pytest.raises(PaddleClientError, match="failed after 2 attempt"):
        client.parse_pdf_chunks(
            chunks,
            model="PaddleOCR-VL-1.6",
            on_chunk_start=lambda *_args: None,
            on_status=lambda *_args: None,
            should_cancel=lambda: False,
            submit_timeout_seconds=10,
            wait_timeout_seconds=10,
        )


def test_oversized_single_page_retry_is_rasterized(tmp_path: Path) -> None:
    image_path = tmp_path / "noise.png"
    Image.effect_noise((1200, 1200), 100).convert("RGB").save(image_path)

    source = tmp_path / "large-page.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=image_path)
        doc.save(source)

    chunk = split_pdf_chunks(source, tmp_path / "chunks", chunk_pages=1)[0]
    retry_chunks = _retry_chunks_for(chunk, attempt=2, target_bytes=1, raster_dpi=96)

    assert len(retry_chunks) == 1
    assert retry_chunks[0].variant == "rasterized_pdf"
    assert retry_chunks[0].path.exists()
    assert retry_chunks[0].path.stat().st_size < chunk.path.stat().st_size
