from __future__ import annotations

from pathlib import Path

from .config import Settings


def ensure_data_dirs(settings: Settings) -> None:
    for name in ("uploads", "ocr", "pages", "epubs", "logs"):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)


def job_upload_dir(settings: Settings, job_id: str) -> Path:
    return settings.data_dir / "uploads" / job_id


def job_ocr_dir(settings: Settings, job_id: str) -> Path:
    return settings.data_dir / "ocr" / job_id


def job_pages_dir(settings: Settings, job_id: str) -> Path:
    return settings.data_dir / "pages" / job_id


def job_epub_dir(settings: Settings, job_id: str) -> Path:
    return settings.data_dir / "epubs" / job_id


def job_log_path(settings: Settings, job_id: str) -> Path:
    return settings.data_dir / "logs" / f"{job_id}.log"


def job_dirs(settings: Settings, job_id: str) -> list[Path]:
    return [
        job_upload_dir(settings, job_id),
        job_ocr_dir(settings, job_id),
        job_pages_dir(settings, job_id),
        job_epub_dir(settings, job_id),
    ]
