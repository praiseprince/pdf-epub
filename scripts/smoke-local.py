from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_app.config import Settings
from local_app.database import JobStore
from local_app.llm_options import normalize_math_repair_provider
from local_app.paths import ensure_data_dirs, job_upload_dir
from local_app.pdf_tools import pdfinfo
from local_app.worker import JobWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local conversion smoke test against a real PDF.")
    parser.add_argument("--pdf", required=True, type=Path, help="Path to an existing real PDF.")
    parser.add_argument("--data-dir", type=Path, default=Path("tmp/local-smoke-data"))
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--conversion-mode", choices=["document", "comic"], default="document")
    parser.add_argument("--comic-output-format", choices=["kepub", "epub", "cbz"], default="kepub")
    parser.add_argument("--comic-layout", choices=["manga", "comic", "webtoon"], default="webtoon")
    parser.add_argument(
        "--math-repair",
        choices=["off", "gemini", "baidu", "gemini_baidu", "baidu_gemini"],
        default="off",
    )
    parser.add_argument("--snapshot-dpi", type=int, default=96)
    parser.add_argument("--allow-small", action="store_true", help="Allow PDFs under 100 pages.")
    parser.add_argument("--epubcheck", action="store_true", help="Run EPUBCheck when EPUBCHECK_JAR is available.")
    parser.add_argument("--kepub", action="store_true", help="Also create and validate a .kepub.epub copy.")
    parser.add_argument("--fresh", action="store_true", help="Clear the smoke-test data directory first.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_pdf = args.pdf.resolve()
    if not source_pdf.exists():
        print(f"PDF not found: {source_pdf}", file=sys.stderr)
        return 1

    info = pdfinfo(source_pdf)
    pages = int(info.get("pages", 0) or 0)
    if pages < 100 and not args.allow_small:
        print(f"Smoke PDF has {pages} pages; use a 100+ page real PDF or pass --allow-small.", file=sys.stderr)
        return 1

    data_dir = args.data_dir.resolve()
    if args.fresh and data_dir.exists():
        if "tmp" not in data_dir.parts:
            print(f"Refusing to clear non-tmp data dir: {data_dir}", file=sys.stderr)
            return 1
        shutil.rmtree(data_dir)

    settings = Settings(
        local_data_dir=data_dir,
        local_paddle_mode=args.mode,
        snapshot_dpi=args.snapshot_dpi,
        app_pin_hash="smoke-test",
        session_secret="smoke-test-session-secret",
    )
    ensure_data_dirs(settings)
    store = JobStore(settings.database_path)
    worker = JobWorker(settings, store)

    job_id = "smoke-" + source_pdf.stem.replace(" ", "-").lower()[:40]
    upload_dir = job_upload_dir(settings, job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = upload_dir / "source.pdf"
    shutil.copy2(source_pdf, target_pdf)

    existing = store.maybe_get_job(job_id)
    if existing:
        store.delete_job(job_id)

    job = store.create_job(
        job_id=job_id,
        source_filename=source_pdf.name,
        title=source_pdf.stem,
        author="",
        size_bytes=source_pdf.stat().st_size,
        include_snapshots=True,
        create_kepub=args.kepub and args.conversion_mode == "document",
        conversion_mode=args.conversion_mode,
        comic_output_format=args.comic_output_format,
        comic_layout=args.comic_layout,
        math_repair_provider=normalize_math_repair_provider(args.math_repair) if args.conversion_mode == "document" else "off",
        source_path=target_pdf,
    )
    worker._process_job(job.id)
    finished = store.get_job(job.id)

    print(f"job={finished.id}")
    print(f"status={finished.status}")
    print(f"stage={finished.stage}")
    print(f"pages={finished.pages}")
    print(f"message={finished.message}")
    if finished.error:
        print(f"note={finished.error}")

    if finished.status != "done" or not finished.epub_path:
        return 1

    output_path = Path(finished.epub_path)
    print(f"output={output_path}")
    kepub_path = output_path.with_name(f"{output_path.stem}.kepub.epub")
    if kepub_path.exists():
        print(f"kepub={kepub_path}")
    print(f"output_size={output_path.stat().st_size}")
    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        first = names[0]
        page_files = [name for name in names if name.startswith("EPUB/text/page-") or name.startswith("OEBPS/Text/")]
        image_files = [
            name
            for name in names
            if name.startswith("EPUB/pages/page-")
            or name.startswith("OEBPS/Images/")
            or name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
    print(f"first_zip_entry={first}")
    print(f"xhtml_pages={len(page_files)}")
    print(f"image_files={len(image_files)}")

    if args.epubcheck:
        jar = settings.epubcheck_jar or Path("tmp/epubcheck-5.3.0/epubcheck.jar").resolve()
        if output_path.name.endswith(".epub") and jar.exists():
            subprocess.run(["java", "-jar", str(jar), str(output_path)], check=True)
            if kepub_path.exists():
                subprocess.run(["java", "-jar", str(jar), str(kepub_path)], check=True)
        elif not output_path.name.endswith(".epub"):
            print("epubcheck skipped; output is not an EPUB")
        else:
            print(f"epubcheck skipped; jar not found at {jar}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
