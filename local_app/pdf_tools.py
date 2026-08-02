from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class PdfToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfChunk:
    index: int
    start_page: int
    end_page: int
    path: Path

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def label(self) -> str:
        if self.start_page == self.end_page:
            return str(self.start_page)
        return f"{self.start_page}-{self.end_page}"


def pdfinfo(pdf_path: Path) -> dict[str, int | str]:
    try:
        import fitz
    except ImportError as exc:
        raise PdfToolError("PyMuPDF is required for PDF inspection. Install requirements and try again.") from exc

    try:
        with fitz.open(pdf_path) as doc:
            metadata = doc.metadata or {}
            info: dict[str, int | str] = {
                "pages": doc.page_count,
                "file_size": pdf_path.stat().st_size,
            }
            for key, value in metadata.items():
                if value:
                    info[key.strip().lower().replace(" ", "_")] = str(value).strip()
            return info
    except Exception as exc:
        raise PdfToolError(f"Could not inspect PDF: {exc}") from exc


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 120,
    scale_to_width: int | None = None,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[Path]:
    try:
        import fitz
    except ImportError as exc:
        raise PdfToolError("PyMuPDF is required for PDF rendering. Install requirements and try again.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        with fitz.open(pdf_path) as doc:
            start = max(0, (first_page or 1) - 1)
            stop = min(doc.page_count, last_page or doc.page_count)
            for page_index in range(start, stop):
                page = doc.load_page(page_index)
                if scale_to_width:
                    scale = max(0.1, float(scale_to_width) / float(page.rect.width))
                else:
                    scale = max(0.1, float(dpi) / 72.0)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                target = output_dir / f"page-{page_index + 1:06d}.png"
                pixmap.save(target)
                paths.append(target)
    except Exception as exc:
        raise PdfToolError(f"Could not render PDF pages: {exc}") from exc

    return paths


def split_pdf_chunks(
    pdf_path: Path,
    output_dir: Path,
    *,
    chunk_pages: int,
    target_bytes: int | None = None,
) -> list[PdfChunk]:
    try:
        import fitz
    except ImportError as exc:
        raise PdfToolError("PyMuPDF is required for PDF chunk parsing. Install requirements and try again.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_pages = max(1, int(chunk_pages))
    target_bytes = int(target_bytes or 0)
    chunks: list[PdfChunk] = []

    try:
        with fitz.open(pdf_path) as source:
            total_pages = source.page_count
            if target_bytes <= 0:
                for start in range(0, total_pages, chunk_pages):
                    end = min(start + chunk_pages, total_pages)
                    chunks.append(_write_pdf_chunk(source, output_dir, len(chunks) + 1, start, end))
            else:
                start = 0
                size = 0
                for page_index in range(total_pages):
                    page_size = _page_pdf_size(source, page_index)
                    page_count = page_index - start
                    if page_count and (page_count >= chunk_pages or size + page_size > target_bytes):
                        chunks.append(_write_pdf_chunk(source, output_dir, len(chunks) + 1, start, page_index))
                        start = page_index
                        size = 0
                    size += page_size
                if start < total_pages:
                    chunks.append(_write_pdf_chunk(source, output_dir, len(chunks) + 1, start, total_pages))
    except Exception as exc:
        raise PdfToolError(f"Could not split PDF into chunks: {exc}") from exc

    return chunks


def _write_pdf_chunk(source: object, output_dir: Path, index: int, start: int, end: int) -> PdfChunk:
    target = output_dir / f"chunk-{index:03d}-pages-{start + 1:04d}-{end:04d}.pdf"
    import fitz

    with fitz.open() as chunk:
        chunk.insert_pdf(source, from_page=start, to_page=end - 1)
        chunk.save(target, garbage=4, deflate=True)
    return PdfChunk(index=index, start_page=start + 1, end_page=end, path=target)


def _page_pdf_size(source: object, page_index: int) -> int:
    import fitz

    with fitz.open() as single:
        single.insert_pdf(source, from_page=page_index, to_page=page_index)
        return len(single.write(garbage=4, deflate=True))


def _page_sort_key(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 0
