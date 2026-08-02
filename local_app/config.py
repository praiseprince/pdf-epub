from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .parser_options import DEFAULT_PARSER_MODEL, ParserModel


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_pin_hash: str = Field("", alias="APP_PIN_HASH")
    session_secret: str = Field("", alias="SESSION_SECRET")
    baidu_ai_studio_api_key: str = Field(
        "",
        validation_alias=AliasChoices("BAIDU_AI_STUDIO_API_KEY", "PADDLEOCR_ACCESS_TOKEN"),
    )
    local_data_dir: Path = Field(Path("data"), alias="LOCAL_DATA_DIR")
    local_host: str = Field("127.0.0.1", alias="LOCAL_HOST")
    local_port: int = Field(8000, alias="LOCAL_PORT")
    local_paddle_mode: Literal["local", "live", "fixture"] = Field("local", alias="LOCAL_PADDLE_MODE")
    paddle_model: ParserModel = Field(DEFAULT_PARSER_MODEL, alias="LOCAL_PADDLE_MODEL")
    local_paddle_python: Path = Field(Path(".venv_paddleocr/bin/python"), alias="LOCAL_PADDLE_PYTHON")
    local_paddle_pipeline_version: str = Field("v1.6", alias="LOCAL_PADDLE_PIPELINE_VERSION")
    local_paddle_device: str = Field("cpu", alias="LOCAL_PADDLE_DEVICE")
    local_paddle_vl_backend: str = Field("", alias="LOCAL_PADDLE_VL_BACKEND")
    local_paddle_vl_server_url: str = Field("", alias="LOCAL_PADDLE_VL_SERVER_URL")
    local_paddle_vl_api_model_name: str = Field("PaddlePaddle/PaddleOCR-VL-1.6", alias="LOCAL_PADDLE_VL_API_MODEL_NAME")
    local_paddle_vl_max_concurrency: int = Field(4, alias="LOCAL_PADDLE_VL_MAX_CONCURRENCY")
    local_start_mlx: bool = Field(False, alias="LOCAL_START_MLX")
    local_start_tunnel: bool = Field(False, alias="LOCAL_START_TUNNEL")
    local_ocr_dpi: int = Field(120, alias="LOCAL_OCR_DPI")

    max_pdf_size_mb: int = Field(200, alias="MAX_PDF_SIZE_MB")
    max_pdf_pages: int = Field(1000, alias="MAX_PDF_PAGES")
    max_image_size_mb: int = Field(256, alias="MAX_IMAGE_SIZE_MB")
    max_total_asset_mb: int = Field(1024, alias="MAX_TOTAL_ASSET_MB")

    include_page_snapshots: bool = Field(True, alias="LOCAL_INCLUDE_PAGE_SNAPSHOTS")
    create_kepub_default: bool = Field(False, alias="LOCAL_CREATE_KEPUB_DEFAULT")
    snapshot_dpi: int = Field(120, alias="LOCAL_SNAPSHOT_DPI")
    figure_crop_dpi: int = Field(240, alias="LOCAL_FIGURE_CROP_DPI")
    paddle_poll_seconds: float = Field(5.0, alias="LOCAL_PADDLE_POLL_SECONDS")
    paddle_submit_timeout_seconds: int = Field(180, alias="LOCAL_PADDLE_SUBMIT_TIMEOUT_SECONDS")
    paddle_auto_ocr_timeout_seconds: int = Field(300, alias="LOCAL_PADDLE_AUTO_OCR_TIMEOUT_SECONDS")
    paddle_status_timeout_seconds: int = Field(30, alias="LOCAL_PADDLE_STATUS_TIMEOUT_SECONDS")
    paddle_chunk_pages: int = Field(2, alias="LOCAL_PADDLE_CHUNK_PAGES")
    paddle_chunk_target_mb: int = Field(1, alias="LOCAL_PADDLE_CHUNK_TARGET_MB")
    paddle_chunk_concurrency: int = Field(12, alias="LOCAL_PADDLE_CHUNK_CONCURRENCY")
    paddle_chunk_timeout_seconds: int = Field(180, alias="LOCAL_PADDLE_CHUNK_TIMEOUT_SECONDS")
    paddle_chunk_retries: int = Field(1, alias="LOCAL_PADDLE_CHUNK_RETRIES")
    paddle_chunk_retry_raster_dpi: int = Field(160, alias="LOCAL_PADDLE_CHUNK_RETRY_RASTER_DPI")
    paddle_auto_chunk_min_pages: int = Field(20, alias="LOCAL_PADDLE_AUTO_CHUNK_MIN_PAGES")
    paddle_auto_chunk_min_bytes_per_page: int = Field(350_000, alias="LOCAL_PADDLE_AUTO_CHUNK_MIN_BYTES_PER_PAGE")
    paddle_page_submit_timeout_seconds: int = Field(120, alias="LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS")
    paddle_page_submit_retries: int = Field(2, alias="LOCAL_PADDLE_PAGE_SUBMIT_RETRIES")
    worker_poll_seconds: float = Field(1.0, alias="LOCAL_WORKER_POLL_SECONDS")

    kcc_c2e_command: str = Field("", alias="LOCAL_KCC_C2E_COMMAND")
    kcc_source_dir: Path | None = Field(Path("tmp/kcc-source-work"), alias="LOCAL_KCC_SOURCE_DIR")
    kcc_profile: str = Field("KoCC", alias="LOCAL_KCC_PROFILE")
    kcc_render_width: int = Field(1072, alias="LOCAL_KCC_RENDER_WIDTH")
    kcc_force_color: bool = Field(True, alias="LOCAL_KCC_FORCE_COLOR")
    kcc_disable_rotate: bool = Field(True, alias="LOCAL_KCC_DISABLE_ROTATE")

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

    @property
    def paddle_chunk_target_bytes(self) -> int:
        return self.paddle_chunk_target_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
