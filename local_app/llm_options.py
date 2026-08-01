from __future__ import annotations

from typing import Literal


MathRepairProvider = Literal["off", "gemini", "baidu", "gemini_baidu", "baidu_gemini"]

MATH_REPAIR_PROVIDERS: tuple[tuple[MathRepairProvider, str], ...] = (
    ("off", "Off"),
    ("gemini", "Gemini"),
    ("baidu", "Baidu AI Studio"),
    ("gemini_baidu", "Gemini, then Baidu"),
    ("baidu_gemini", "Baidu, then Gemini"),
)

DEFAULT_MATH_REPAIR_PROVIDER: MathRepairProvider = "off"


def normalize_math_repair_provider(value: str | None) -> MathRepairProvider:
    candidate = (value or "").strip().lower().replace("-", "_")
    allowed = {provider for provider, _label in MATH_REPAIR_PROVIDERS}
    return candidate if candidate in allowed else DEFAULT_MATH_REPAIR_PROVIDER  # type: ignore[return-value]


def math_repair_provider_label(value: str | None) -> str:
    normalized = normalize_math_repair_provider(value)
    return dict(MATH_REPAIR_PROVIDERS).get(normalized, "Off")


def provider_chain(value: MathRepairProvider) -> tuple[str, ...]:
    if value == "gemini":
        return ("gemini",)
    if value == "baidu":
        return ("baidu",)
    if value == "gemini_baidu":
        return ("gemini", "baidu")
    if value == "baidu_gemini":
        return ("baidu", "gemini")
    return ()
