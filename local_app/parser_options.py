from __future__ import annotations

from typing import Literal


ParserModel = Literal["PaddleOCR-VL-1.6"]
ParserStrategy = Literal["auto", "full_document", "pdf_chunks", "rendered_pages"]

PARSER_MODELS: tuple[ParserModel, ...] = (
    "PaddleOCR-VL-1.6",
)
PARSER_STRATEGIES: tuple[ParserStrategy, ...] = ("auto", "full_document", "pdf_chunks", "rendered_pages")

DEFAULT_PARSER_MODEL: ParserModel = "PaddleOCR-VL-1.6"
DEFAULT_PARSER_STRATEGY: ParserStrategy = "auto"


def normalize_parser_model(value: str | None) -> ParserModel:
    if value in PARSER_MODELS:
        return value  # type: ignore[return-value]
    return DEFAULT_PARSER_MODEL


def normalize_parser_strategy(value: str | None) -> ParserStrategy:
    if value in PARSER_STRATEGIES:
        return value  # type: ignore[return-value]
    return DEFAULT_PARSER_STRATEGY
