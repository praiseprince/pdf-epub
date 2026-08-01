from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import Settings
from .llm_options import MathRepairProvider, normalize_math_repair_provider, provider_chain


PROVIDER_LABELS = {
    "gemini": "Gemini",
    "baidu": "Baidu AI Studio",
}

SYSTEM_PROMPT = """You repair OCR-damaged LaTeX snippets so MathJax can compile them.
Fix syntax only. Preserve the original mathematical meaning, symbols, variable names, numbering, and order.
Do not simplify, solve, explain, translate, invent missing equations, or add surrounding prose.
Return JSON only, with this shape:
{"repairs":[{"id":"same id","latex":"compilable LaTeX without dollar delimiters","confidence":"high|medium|low"}]}
Use confidence "low" if the input is too damaged to repair without guessing."""


class MathRepairError(RuntimeError):
    pass


class MathRepairClient:
    def __init__(self, settings: Settings, provider: str | None):
        self.settings = settings
        self.provider = normalize_math_repair_provider(provider)

    def repair_failed_formulas(self, failures: list[dict[str, Any]], warnings: list[str]) -> dict[str, str]:
        formulas = _repairable_failures(failures)
        if not formulas or self.provider == "off":
            return {}

        limit = max(0, self.settings.llm_max_failed_formulas_per_job)
        if limit and len(formulas) > limit:
            warnings.append(
                f"AI math repair skipped {len(formulas) - limit} formula(s) beyond LOCAL_LLM_MAX_FAILED_FORMULAS_PER_JOB."
            )
            formulas = formulas[:limit]

        repairs: dict[str, str] = {}
        unresolved = formulas
        for provider in provider_chain(self.provider):
            if not unresolved:
                break
            try:
                text = self._request_provider(provider, unresolved)
                provider_repairs = _extract_repairs(text, unresolved)
            except MathRepairError as exc:
                warnings.append(f"{PROVIDER_LABELS.get(provider, provider)} math repair failed: {exc}")
                continue

            if provider_repairs:
                warnings.append(
                    f"{PROVIDER_LABELS.get(provider, provider)} returned {len(provider_repairs)} math repair candidate(s)."
                )
            repairs.update(provider_repairs)
            unresolved = [item for item in unresolved if str(item["key"]) not in provider_repairs]

        return repairs

    def _request_provider(self, provider: str, formulas: list[dict[str, Any]]) -> str:
        if provider == "gemini":
            return self._request_gemini(formulas)
        if provider == "baidu":
            return self._request_baidu(formulas)
        raise MathRepairError(f"Unknown provider {provider}.")

    def _request_gemini(self, formulas: list[dict[str, Any]]) -> str:
        if not self.settings.gemini_api_key:
            raise MathRepairError("GEMINI_API_KEY is not configured.")

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _repair_payload(formulas)}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": _max_output_tokens(formulas),
                "responseMimeType": "application/json",
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
        try:
            with httpx.Client(timeout=self.settings.llm_request_timeout_seconds) as client:
                response = client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MathRepairError(_http_error(exc.response)) from exc
        except httpx.HTTPError as exc:
            raise MathRepairError(str(exc)) from exc

        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise MathRepairError("Gemini returned an unexpected response shape.") from exc

    def _request_baidu(self, formulas: list[dict[str, Any]]) -> str:
        if not self.settings.baidu_ai_studio_api_key:
            raise MathRepairError("BAIDU_AI_STUDIO_API_KEY is not configured.")

        base_url = self.settings.baidu_ai_studio_base_url.rstrip("/")
        payload = {
            "model": self.settings.baidu_ai_studio_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _repair_payload(formulas)},
            ],
            "temperature": 0,
            "max_tokens": _max_output_tokens(formulas),
        }
        try:
            with httpx.Client(timeout=self.settings.llm_request_timeout_seconds) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.baidu_ai_studio_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MathRepairError(_http_error(exc.response)) from exc
        except httpx.HTTPError as exc:
            raise MathRepairError(str(exc)) from exc

        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise MathRepairError("Baidu AI Studio returned an unexpected response shape.") from exc


def _repairable_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formulas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in failures:
        key = str(item.get("key") or "")
        latex = str(item.get("latex") or "").strip()
        if not key or not latex or key in seen:
            continue
        formulas.append(
            {
                "key": key,
                "latex": latex,
                "display": bool(item.get("display")),
                "error": str(item.get("error") or "")[:500],
            }
        )
        seen.add(key)
    return formulas


def _repair_payload(formulas: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task": "Repair only the LaTeX syntax. Return JSON only.",
            "formulas": [
                {
                    "id": str(item["key"]),
                    "latex": str(item["latex"]),
                    "display": bool(item["display"]),
                    "mathjax_error": str(item.get("error") or ""),
                }
                for item in formulas
            ],
        },
        ensure_ascii=False,
    )


def _max_output_tokens(formulas: list[dict[str, Any]]) -> int:
    return min(8192, max(1024, 160 * max(1, len(formulas))))


def _extract_repairs(text: str, failures: list[dict[str, Any]]) -> dict[str, str]:
    data = _load_json_object(text)
    source_by_id = {str(item["key"]): str(item["latex"]) for item in failures}
    raw_items = data.get("repairs") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raise MathRepairError("AI response did not contain a repairs list.")

    repairs: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or item.get("key") or "").strip()
        if key not in source_by_id:
            continue
        confidence = str(item.get("confidence") or "medium").lower()
        if confidence == "low":
            continue
        latex = _clean_latex(str(item.get("latex") or ""))
        if _valid_repair(latex, source_by_id[key]):
            repairs[key] = latex
    return repairs


def _load_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError as exc:
                raise MathRepairError("AI response was not valid JSON.") from exc
        raise MathRepairError("AI response was not valid JSON.")


def _clean_latex(value: str) -> str:
    latex = value.strip()
    wrappers = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$"))
    changed = True
    while changed:
        changed = False
        for start, end in wrappers:
            if latex.startswith(start) and latex.endswith(end) and len(latex) > len(start) + len(end):
                latex = latex[len(start) : -len(end)].strip()
                changed = True
    return latex


def _valid_repair(candidate: str, source: str) -> bool:
    if not candidate or candidate == source.strip():
        return False
    if len(candidate) > max(1200, len(source) * 4 + 120):
        return False
    if re.search(r"</?[A-Za-z][^>]*>", candidate):
        return False
    if "\x00" in candidate:
        return False
    return True


def _http_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        detail = response.text.strip()
    else:
        detail = json.dumps(body, ensure_ascii=False)[:700]
    return f"HTTP {response.status_code}: {detail or response.reason_phrase}"
