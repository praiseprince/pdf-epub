from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class PdfToolError(RuntimeError):
    pass


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
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise PdfToolError("Poppler pdftoppm is required. Install poppler and try again.")

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "page"
    command = [executable, "-png", "-r", str(dpi)]
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


def _page_sort_key(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 0
