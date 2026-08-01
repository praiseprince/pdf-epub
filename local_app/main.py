from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .database import JobStore, serialize_jobs
from .paths import ensure_data_dirs, job_upload_dir
from .security import clear_session_cookie, read_session, require_api_session, set_session_cookie, verify_pin
from .worker import JobWorker, delete_job_files


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_data_dirs(settings)
    store = JobStore(settings.database_path)
    worker = JobWorker(settings, store)
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


app = FastAPI(title="Local PDF to EPUB", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def store_dep(request: Request) -> JobStore:
    return request.app.state.store


def worker_dep(request: Request) -> JobWorker:
    return request.app.state.worker


def api_auth(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    require_api_session(request, settings)


@app.get("/", include_in_schema=False)
async def home(request: Request, settings: Settings = Depends(settings_dep)) -> RedirectResponse:
    if read_session(request, settings):
        return RedirectResponse("/convert", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings: Settings = Depends(settings_dep)) -> HTMLResponse:
    if read_session(request, settings):
        return RedirectResponse("/convert", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"missing_config": not bool(settings.app_pin_hash and settings.session_secret), "error": ""},
    )


@app.post("/login")
async def login(
    request: Request,
    pin: str = Form(...),
    settings: Settings = Depends(settings_dep),
) -> Response:
    if not verify_pin(pin, settings):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"missing_config": not bool(settings.app_pin_hash and settings.session_secret), "error": "Invalid PIN."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse("/convert", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, settings)
    return response


@app.post("/logout")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response


@app.get("/convert", response_class=HTMLResponse)
async def convert_page(request: Request, settings: Settings = Depends(settings_dep)) -> HTMLResponse:
    if read_session(request, settings) is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "convert.html",
        {
            "max_pdf_size_mb": settings.max_pdf_size_mb,
            "max_pdf_pages": settings.max_pdf_pages,
            "paddle_mode": settings.local_paddle_mode,
        },
    )


@app.get("/api/jobs")
async def list_jobs(
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
) -> dict[str, object]:
    return {"jobs": serialize_jobs(store.list_jobs())}


@app.get("/api/jobs/{job_id}")
async def get_job(
    job_id: str,
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
) -> dict[str, object]:
    job = store.maybe_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.to_dict()}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    _: None = Depends(api_auth),
    settings: Settings = Depends(settings_dep),
    store: JobStore = Depends(store_dep),
    worker: JobWorker = Depends(worker_dep),
) -> JSONResponse:
    filename = _safe_filename(file.filename or "document.pdf")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    job_id = str(uuid.uuid4())
    upload_dir = job_upload_dir(settings, job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / "source.pdf"
    size = 0
    with source_path.open("wb") as stream:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            stream.write(chunk)

    job = store.create_job(
        job_id=job_id,
        source_filename=filename,
        title=_clean_metadata(title) or Path(filename).stem,
        author=_clean_metadata(author),
        size_bytes=size,
        include_snapshots=True,
        source_path=source_path,
    )
    await worker.enqueue(job.id)
    return JSONResponse({"job": job.to_dict()}, status_code=status.HTTP_201_CREATED)


@app.patch("/api/jobs/{job_id}")
async def update_job(
    job_id: str,
    payload: dict[str, str],
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
) -> dict[str, object]:
    job = store.maybe_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    fields = {}
    if "title" in payload:
        fields["title"] = _clean_metadata(payload["title"]) or job.title
    if "author" in payload:
        fields["author"] = _clean_metadata(payload["author"])
    return {"job": store.update_job(job_id, **fields).to_dict()}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
) -> dict[str, object]:
    if not store.maybe_get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": store.request_cancel(job_id).to_dict()}


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
    worker: JobWorker = Depends(worker_dep),
) -> dict[str, object]:
    job = store.maybe_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    reset = store.reset_for_retry(job_id)
    await worker.enqueue(job_id)
    return {"job": reset.to_dict()}


@app.delete("/api/jobs/{job_id}")
async def delete_job(
    job_id: str,
    _: None = Depends(api_auth),
    settings: Settings = Depends(settings_dep),
    store: JobStore = Depends(store_dep),
) -> dict[str, object]:
    if not store.maybe_get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    store.request_cancel(job_id)
    delete_job_files(settings, job_id)
    store.delete_job(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
async def download_job(
    job_id: str,
    _: None = Depends(api_auth),
    store: JobStore = Depends(store_dep),
) -> FileResponse:
    job = store.maybe_get_job(job_id)
    if not job or not job.epub_path:
        raise HTTPException(status_code=404, detail="EPUB not found")
    path = Path(job.epub_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="EPUB file missing")
    filename = f"{Path(job.source_filename).stem}.epub"
    return FileResponse(path, media_type="application/epub+zip", filename=filename)


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip() or "document.pdf"
    name = re.sub(r"[^A-Za-z0-9._ -]+", "-", name)
    return name[:160] or "document.pdf"


def _clean_metadata(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())[:200]
