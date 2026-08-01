from __future__ import annotations

from pathlib import Path

from local_app.database import JobStore


def test_job_store_persists_running_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    created = store.create_job(
        job_id="job-1",
        source_filename="paper.pdf",
        title="Paper",
        author="A. Author",
        size_bytes=source.stat().st_size,
        include_snapshots=True,
        create_kepub=True,
        source_path=source,
    )
    store.update_job(created.id, status="running", stage="Reading document")

    reopened = JobStore(tmp_path / "app.db")
    resumed = reopened.jobs_to_resume()

    assert [job.id for job in resumed] == ["job-1"]
    assert resumed[0].stage == "Reading document"
    assert resumed[0].create_kepub is True
