from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_pin_hash: str = Field("", alias="APP_PIN_HASH")
    session_secret: str = Field("", alias="SESSION_SECRET")
    paddleocr_access_token: str = Field("", alias="PADDLEOCR_ACCESS_TOKEN")

    local_data_dir: Path = Field(Path("data"), alias="LOCAL_DATA_DIR")
    local_host: str = Field("127.0.0.1", alias="LOCAL_HOST")
    local_port: int = Field(8000, alias="LOCAL_PORT")
    local_paddle_mode: Literal["live", "fixture"] = Field("live", alias="LOCAL_PADDLE_MODE")

    max_pdf_size_mb: int = Field(200, alias="MAX_PDF_SIZE_MB")
    max_pdf_pages: int = Field(1000, alias="MAX_PDF_PAGES")
    max_image_size_mb: int = Field(256, alias="MAX_IMAGE_SIZE_MB")
    max_total_asset_mb: int = Field(1024, alias="MAX_TOTAL_ASSET_MB")

    include_page_snapshots: bool = Field(True, alias="LOCAL_INCLUDE_PAGE_SNAPSHOTS")
    create_kepub_default: bool = Field(False, alias="LOCAL_CREATE_KEPUB_DEFAULT")
    snapshot_dpi: int = Field(120, alias="LOCAL_SNAPSHOT_DPI")
    paddle_poll_seconds: float = Field(5.0, alias="LOCAL_PADDLE_POLL_SECONDS")
    worker_poll_seconds: float = Field(1.0, alias="LOCAL_WORKER_POLL_SECONDS")

    epubcheck_jar: Path | None = Field(None, alias="EPUBCHECK_JAR")

    @property
    def data_dir(self) -> Path:
        return self.local_data_dir.expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024

    @property
    def max_image_size_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024

    @property
    def max_total_asset_bytes(self) -> int:
        return self.max_total_asset_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
