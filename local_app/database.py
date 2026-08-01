from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class JobRecord:
    id: str
    source_filename: str
    title: str
    author: str
    status: str
    stage: str
    message: str
    progress_done: int
    progress_total: int
    pages: int | None
    size_bytes: int
    paddle_job_id: str | None
    include_snapshots: bool
    create_kepub: bool
    source_path: str
    raw_result_path: str | None
    epub_path: str | None
    error: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_filename": self.source_filename,
            "title": self.title,
            "author": self.author,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress_done": self.progress_done,
            "progress_total": self.progress_total,
            "pages": self.pages,
            "size_bytes": self.size_bytes,
            "paddle_job_id": self.paddle_job_id,
            "include_snapshots": self.include_snapshots,
            "has_epub": bool(self.epub_path),
            "create_kepub": self.create_kepub,
            "has_kepub": bool(self.epub_path and _kepub_path(self.epub_path).exists()),
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  source_filename TEXT NOT NULL,
                  title TEXT NOT NULL,
                  author TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  message TEXT NOT NULL DEFAULT '',
                  progress_done INTEGER NOT NULL DEFAULT 0,
                  progress_total INTEGER NOT NULL DEFAULT 0,
                  pages INTEGER,
                  size_bytes INTEGER NOT NULL DEFAULT 0,
                  paddle_job_id TEXT,
                  include_snapshots INTEGER NOT NULL DEFAULT 1,
                  create_kepub INTEGER NOT NULL DEFAULT 0,
                  source_path TEXT NOT NULL,
                  raw_result_path TEXT,
                  epub_path TEXT,
                  error TEXT,
                  cancel_requested INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT
                )
                """
            )
            _ensure_column(conn, "jobs", "create_kepub", "INTEGER NOT NULL DEFAULT 0")

    def create_job(
        self,
        *,
        job_id: str,
        source_filename: str,
        title: str,
        author: str,
        size_bytes: int,
        include_snapshots: bool,
        create_kepub: bool,
        source_path: Path,
    ) -> JobRecord:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                  id, source_filename, title, author, status, stage, message,
                  size_bytes, include_snapshots, create_kepub, source_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'queued', 'Queued', 'Waiting for the local worker.',
                        ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_filename,
                    title,
                    author,
                    size_bytes,
                    1 if include_snapshots else 0,
                    1 if create_kepub else 0,
                    str(source_path),
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _row_to_job(row)

    def maybe_get_job(self, job_id: str) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY datetime(created_at) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def jobs_to_resume(self) -> list[JobRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('queued', 'running')
                ORDER BY datetime(created_at) ASC
                """
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> JobRecord:
        if not fields:
            return self.get_job(job_id)

        normalized = {key: _db_value(value) for key, value in fields.items()}
        normalized["updated_at"] = utc_now()
        set_clause = ", ".join(f"{key} = ?" for key in normalized)
        values = list(normalized.values())
        values.append(job_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        return self.get_job(job_id)

    def request_cancel(self, job_id: str) -> JobRecord:
        return self.update_job(
            job_id,
            cancel_requested=True,
            message="Cancel requested. The worker will stop at the next stage boundary.",
        )

    def reset_for_retry(self, job_id: str) -> JobRecord:
        return self.update_job(
            job_id,
            status="queued",
            stage="Queued",
            message="Waiting for the local worker.",
            progress_done=0,
            progress_total=0,
            paddle_job_id=None,
            raw_result_path=None,
            epub_path=None,
            error=None,
            cancel_requested=False,
            started_at=None,
            finished_at=None,
        )

    def delete_job(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def _db_value(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Path):
        return str(value)
    return value


def _row_to_job(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        source_filename=row["source_filename"],
        title=row["title"],
        author=row["author"],
        status=row["status"],
        stage=row["stage"],
        message=row["message"],
        progress_done=row["progress_done"],
        progress_total=row["progress_total"],
        pages=row["pages"],
        size_bytes=row["size_bytes"],
        paddle_job_id=row["paddle_job_id"],
        include_snapshots=bool(row["include_snapshots"]),
        create_kepub=bool(row["create_kepub"]),
        source_path=row["source_path"],
        raw_result_path=row["raw_result_path"],
        epub_path=row["epub_path"],
        error=row["error"],
        cancel_requested=bool(row["cancel_requested"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def serialize_jobs(jobs: Iterable[JobRecord]) -> list[dict[str, Any]]:
    return [job.to_dict() for job in jobs]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _kepub_path(epub_path: str) -> Path:
    path = Path(epub_path)
    return path.with_name(f"{path.stem}.kepub.epub")
