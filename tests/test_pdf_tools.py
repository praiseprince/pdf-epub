from __future__ import annotations

from pathlib import Path

import fitz

from local_app.pdf_tools import pdfinfo, render_pdf_pages, split_pdf_chunks
from local_app.parser_options import normalize_parser_strategy


def test_split_pdf_chunks_preserves_page_ranges(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for page_number in range(5):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"Page {page_number + 1}")
        doc.save(source)

    chunks = split_pdf_chunks(source, tmp_path / "chunks", chunk_pages=2)

    assert [chunk.label for chunk in chunks] == ["1-2", "3-4", "5"]
    assert all(chunk.path.exists() for chunk in chunks)
    page_counts: list[int] = []
    for chunk in chunks:
        with fitz.open(chunk.path) as doc:
            page_counts.append(doc.page_count)
    assert page_counts == [2, 2, 1]


def test_pdfinfo_reads_metadata_with_pymupdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.set_metadata({"title": "Sample Title", "author": "June"})
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), "Page 1")
        doc.save(source)

    info = pdfinfo(source)

    assert info["pages"] == 1
    assert info["title"] == "Sample Title"
    assert info["author"] == "June"
    assert int(info["file_size"]) > 0


def test_render_pdf_pages_uses_pymupdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for page_number in range(2):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"Page {page_number + 1}")
        doc.save(source)

    paths = render_pdf_pages(source, tmp_path / "pages", dpi=72, first_page=2, last_page=2)

    assert [path.name for path in paths] == ["page-000002.png"]
    assert paths[0].exists()


def test_split_pdf_chunks_respects_target_size_when_possible(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for page_number in range(5):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"Page {page_number + 1}")
        doc.save(source)

    chunks = split_pdf_chunks(source, tmp_path / "sized", chunk_pages=5, target_bytes=1)

    assert [chunk.label for chunk in chunks] == ["1", "2", "3", "4", "5"]


def test_pdf_chunks_parser_strategy_is_accepted() -> None:
    assert normalize_parser_strategy("pdf_chunks") == "pdf_chunks"
