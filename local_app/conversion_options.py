from __future__ import annotations

from typing import Literal


ConversionMode = Literal["document", "comic"]
ComicOutputFormat = Literal["kepub", "epub", "cbz"]
ComicLayout = Literal["manga", "comic", "webtoon"]

CONVERSION_MODES: tuple[ConversionMode, ...] = ("document", "comic")
COMIC_OUTPUT_FORMATS: tuple[ComicOutputFormat, ...] = ("kepub", "epub", "cbz")
COMIC_LAYOUTS: tuple[ComicLayout, ...] = ("manga", "comic", "webtoon")

DEFAULT_CONVERSION_MODE: ConversionMode = "document"
DEFAULT_COMIC_OUTPUT_FORMAT: ComicOutputFormat = "kepub"
DEFAULT_COMIC_LAYOUT: ComicLayout = "webtoon"


def normalize_conversion_mode(value: str | None) -> ConversionMode:
    candidate = (value or "").strip().lower()
    return candidate if candidate in CONVERSION_MODES else DEFAULT_CONVERSION_MODE  # type: ignore[return-value]


def normalize_comic_output_format(value: str | None) -> ComicOutputFormat:
    candidate = (value or "").strip().lower()
    return candidate if candidate in COMIC_OUTPUT_FORMATS else DEFAULT_COMIC_OUTPUT_FORMAT  # type: ignore[return-value]


def normalize_comic_layout(value: str | None) -> ComicLayout:
    candidate = (value or "").strip().lower()
    return candidate if candidate in COMIC_LAYOUTS else DEFAULT_COMIC_LAYOUT  # type: ignore[return-value]
