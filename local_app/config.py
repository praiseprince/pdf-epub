from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .llm_options import DEFAULT_MATH_REPAIR_PROVIDER, MathRepairProvider
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
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-3.1-flash-lite", alias="GEMINI_MODEL")
    baidu_ai_studio_base_url: str = Field("https://aistudio.baidu.com/llm/lmapi/v3", alias="BAIDU_AI_STUDIO_BASE_URL")
    baidu_ai_studio_model: str = Field("ernie-4.5-turbo-128k", alias="BAIDU_AI_STUDIO_MODEL")

    local_data_dir: Path = Field(Path("data"), alias="LOCAL_DATA_DIR")
    local_host: str = Field("127.0.0.1", alias="LOCAL_HOST")
    local_port: int = Field(8000, alias="LOCAL_PORT")
    local_paddle_mode: Literal["live", "fixture"] = Field("live", alias="LOCAL_PADDLE_MODE")
    paddle_model: ParserModel = Field(DEFAULT_PARSER_MODEL, alias="LOCAL_PADDLE_MODEL")

    max_pdf_size_mb: int = Field(200, alias="MAX_PDF_SIZE_MB")
    max_pdf_pages: int = Field(1000, alias="MAX_PDF_PAGES")
    max_image_size_mb: int = Field(256, alias="MAX_IMAGE_SIZE_MB")
    max_total_asset_mb: int = Field(1024, alias="MAX_TOTAL_ASSET_MB")

    include_page_snapshots: bool = Field(True, alias="LOCAL_INCLUDE_PAGE_SNAPSHOTS")
    create_kepub_default: bool = Field(False, alias="LOCAL_CREATE_KEPUB_DEFAULT")
    snapshot_dpi: int = Field(120, alias="LOCAL_SNAPSHOT_DPI")
    paddle_poll_seconds: float = Field(5.0, alias="LOCAL_PADDLE_POLL_SECONDS")
    paddle_submit_timeout_seconds: int = Field(300, alias="LOCAL_PADDLE_SUBMIT_TIMEOUT_SECONDS")
    paddle_page_submit_timeout_seconds: int = Field(120, alias="LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS")
    paddle_page_submit_retries: int = Field(2, alias="LOCAL_PADDLE_PAGE_SUBMIT_RETRIES")
    worker_poll_seconds: float = Field(1.0, alias="LOCAL_WORKER_POLL_SECONDS")
    math_repair_provider: MathRepairProvider = Field(
        DEFAULT_MATH_REPAIR_PROVIDER,
        alias="LOCAL_MATH_REPAIR_PROVIDER",
    )
    llm_request_timeout_seconds: int = Field(60, alias="LOCAL_LLM_REQUEST_TIMEOUT_SECONDS")
    llm_max_failed_formulas_per_job: int = Field(200, alias="LOCAL_LLM_MAX_FAILED_FORMULAS_PER_JOB")

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
