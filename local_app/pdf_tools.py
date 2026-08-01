from __future__ import annotations

import re
import shutil
import subprocess
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
    executable = shutil.which("pdfinfo")
    if not executable:
        raise PdfToolError("Poppler pdfinfo is required. Install poppler and try again.")

    proc = subprocess.run(
        [executable, str(pdf_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PdfToolError(proc.stderr.strip() or "pdfinfo failed.")

    info: dict[str, int | str] = {}
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if key in {"pages", "file_size"}:
            match = re.search(r"\d+", value)
            if match:
                info[key] = int(match.group(0))
        else:
            info[key] = value
    return info


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 120,
    scale_to_width: int | None = None,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise PdfToolError("Poppler pdftoppm is required. Install poppler and try again.")

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "page"
    command = [executable, "-png"]
    if scale_to_width:
        command.extend(["-scale-to-x", str(scale_to_width), "-scale-to-y", "-1"])
    else:
        command.extend(["-r", str(dpi)])
    if first_page is not None:
        command.extend(["-f", str(first_page)])
    if last_page is not None:
        command.extend(["-l", str(last_page)])
    command.extend([str(pdf_path), str(prefix)])

    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PdfToolError(proc.stderr.strip() or "pdftoppm failed.")

    return sorted(output_dir.glob("page-*.png"), key=_page_sort_key)


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
