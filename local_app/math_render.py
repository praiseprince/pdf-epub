from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from PIL import Image

from .assets import AssetBundle


@dataclass(frozen=True)
class MathToken:
    latex: str
    display: bool


class MathRepairer(Protocol):
    def repair_failed_formulas(self, failures: list[dict[str, Any]], warnings: list[str]) -> dict[str, str]:
        ...


class MathRenderer:
    def __init__(self, output_dir: Path, repairer: MathRepairer | None = None):
        self.output_dir = output_dir
        self.repairer = repairer
        self.helper_path = Path(__file__).parent / "node" / "math_render.mjs"
        self.cache: dict[MathToken, str] = {}
        self.dimensions: dict[MathToken, tuple[int, int]] = {}

    def render_many(self, tokens: Iterable[MathToken], warnings: list[str]) -> AssetBundle:
        unique_tokens = list(dict.fromkeys(token for token in tokens if token.latex.strip()))
        pending: list[dict[str, Any]] = []

        for token in unique_tokens:
            key = self._key(token)
            filename = f"{key}.png"
            target = self.output_dir / filename
            if not target.exists():
                pending.append(
                    {
                        "key": key,
                        "latex": token.latex,
                        "display": token.display,
                        "filename": filename,
                    }
                )

        failures: list[dict[str, Any]] = []
        if pending:
            failures = self._render_batch(pending, warnings)
            if failures and self.repairer:
                repairs = self.repairer.repair_failed_formulas(failures, warnings)
                repaired_pending = []
                for item in failures:
                    repaired_latex = repairs.get(str(item["key"]))
                    if repaired_latex:
                        repaired_item = dict(item)
                        repaired_item["latex"] = repaired_latex
                        repaired_pending.append(repaired_item)
                if repaired_pending:
                    repaired_failures = self._render_batch(repaired_pending, warnings)
                    repaired_failed_keys = {str(item.get("key")) for item in repaired_failures}
                    repaired_count = len(repaired_pending) - len(repaired_failed_keys)
                    if repaired_count:
                        warnings.append(f"{repaired_count} formula(s) rendered after AI math repair.")
                    failures = [
                        item
                        for item in failures
                        if str(item.get("key")) not in repairs or str(item.get("key")) in repaired_failed_keys
                    ]

        bundle = self._bundle_existing_outputs(unique_tokens)
        missing_count = len(unique_tokens) - len(bundle.manifest_items)
        if missing_count:
            warnings.append(f"{missing_count} formula(s) could not be rendered.")
        return bundle

    def _render_batch(self, formulas: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["node", str(self.helper_path)],
            input=json.dumps({"outputDir": str(self.output_dir), "formulas": formulas}),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            warnings.append(proc.stderr.strip() or "Formula rendering failed.")
            return [dict(item, error=proc.stderr.strip() or "Formula rendering failed.") for item in formulas]

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            warnings.append("Formula renderer returned invalid JSON.")
            return [dict(item, error="Formula renderer returned invalid JSON.") for item in formulas]

        result_by_key = {str(item.get("key")): item for item in result.get("results", []) if isinstance(item, dict)}
        failures = []
        for item in formulas:
            rendered = result_by_key.get(str(item["key"]))
            if rendered and rendered.get("ok"):
                continue
            failure = dict(item)
            if rendered and rendered.get("error"):
                failure["error"] = str(rendered["error"])
            else:
                failure["error"] = "Formula renderer did not return a success result."
            failures.append(failure)
        return failures

    def _bundle_existing_outputs(self, tokens: list[MathToken]) -> AssetBundle:
        bundle = AssetBundle()
        for token in tokens:
            key = self._key(token)
            filename = f"{key}.png"
            target = self.output_dir / filename
            if not target.exists():
                self.cache.pop(token, None)
                self.dimensions.pop(token, None)
                continue
            href = f"assets/math/{filename}"
            self.cache[token] = href
            self.dimensions[token] = _image_size(target)
            bundle.image_map[f"math:{key}"] = href
            bundle.manifest_items[href] = "image/png"
        return bundle

    def html_for(self, token: MathToken) -> str:
        href = self.cache.get(token)
        alt = html.escape(token.latex, quote=True)
        size_attrs = self._size_attrs(token)
        if not href:
            if token.display:
                return f'<pre class="math-source" role="math">{alt}</pre>'
            return f'<span class="math-source" role="math">{alt}</span>'
        if token.display:
            return f'<div class="math-block"><img class="math-display" src="../{href}" alt="{alt}"{size_attrs} /></div>'
        return f'<img class="math-inline" src="../{href}" alt="{alt}"{size_attrs} />'

    def _key(self, token: MathToken) -> str:
        payload = f"math-png-v2\0{'display' if token.display else 'inline'}\0{token.latex}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]

    def _size_attrs(self, token: MathToken) -> str:
        size = self.dimensions.get(token)
        if not size:
            return ""
        width, height = size
        if width <= 0 or height <= 0:
            return ""
        return f' width="{width}" height="{height}"'


def collect_math_tokens(markdown_pages: Iterable[str]) -> list[MathToken]:
    tokens: list[MathToken] = []
    for markdown in markdown_pages:
        rewrite_math(markdown, lambda token: tokens.append(token) or "")
    return tokens


class MathMLRenderer:
    def __init__(self, repairer: MathRepairer | None = None):
        self.repairer = repairer
        self.helper_path = Path(__file__).parent / "node" / "mathml_render.mjs"
        self.cache: dict[MathToken, str] = {}

    def render_many(self, tokens: Iterable[MathToken], warnings: list[str]) -> AssetBundle:
        unique_tokens = list(dict.fromkeys(token for token in tokens if token.latex.strip()))
        pending = [
            {
                "key": self._key(token),
                "latex": token.latex,
                "original_latex": token.latex,
                "display": token.display,
            }
            for token in unique_tokens
            if token not in self.cache
        ]

        failures: list[dict[str, Any]] = []
        if pending:
            failures = self._render_batch(pending, warnings)
            if failures and self.repairer:
                repairs = self.repairer.repair_failed_formulas(failures, warnings)
                repaired_pending = []
                for item in failures:
                    repaired_latex = repairs.get(str(item["key"]))
                    if repaired_latex:
                        repaired_item = dict(item)
                        repaired_item["latex"] = repaired_latex
                        repaired_pending.append(repaired_item)
                if repaired_pending:
                    repaired_failures = self._render_batch(repaired_pending, warnings)
                    repaired_failed_keys = {str(item.get("key")) for item in repaired_failures}
                    repaired_count = len(repaired_pending) - len(repaired_failed_keys)
                    if repaired_count:
                        warnings.append(f"{repaired_count} formula(s) converted to MathML after AI math repair.")
                    failures = [
                        item
                        for item in failures
                        if str(item.get("key")) not in repairs or str(item.get("key")) in repaired_failed_keys
                    ]

        missing_count = sum(1 for token in unique_tokens if token not in self.cache)
        if missing_count:
            warnings.append(f"{missing_count} formula(s) could not be converted to MathML.")
        return AssetBundle()

    def _render_batch(self, formulas: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
        proc = subprocess.run(
            ["node", str(self.helper_path)],
            input=json.dumps({"formulas": formulas}),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            warnings.append(proc.stderr.strip() or "MathML conversion failed.")
            return [dict(item, error=proc.stderr.strip() or "MathML conversion failed.") for item in formulas]

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            warnings.append("MathML renderer returned invalid JSON.")
            return [dict(item, error="MathML renderer returned invalid JSON.") for item in formulas]

        source_by_key = {str(item["key"]): item for item in formulas}
        failures = []
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            source = source_by_key.get(key)
            if not source:
                continue
            token = MathToken(str(source.get("original_latex") or source["latex"]), bool(source["display"]))
            if item.get("ok") and item.get("mathml"):
                self.cache[token] = str(item["mathml"])
            else:
                failure = dict(source)
                failure["error"] = str(item.get("error") or "MathML renderer did not return a success result.")
                failures.append(failure)

        rendered_keys = {self._key(token) for token in self.cache}
        for item in formulas:
            key = str(item["key"])
            if key not in rendered_keys and all(str(failure["key"]) != key for failure in failures):
                failures.append(dict(item, error="MathML renderer did not return a result."))
        return failures

    def html_for(self, token: MathToken) -> str:
        mathml = self.cache.get(token)
        alt = html.escape(token.latex, quote=True)
        if not mathml:
            if token.display:
                return f'<pre class="math-source" role="math">{alt}</pre>'
            return f'<span class="math-source" role="math">{alt}</span>'
        if token.display:
            return f'<div class="math-block mathml-block">{mathml}</div>'
        return f'<span class="mathml-inline">{mathml}</span>'

    def _key(self, token: MathToken) -> str:
        payload = f"mathml-v1\0{'display' if token.display else 'inline'}\0{token.latex}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]


def rewrite_math(markdown: str, replace: Callable[[MathToken], str]) -> str:
    out: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in markdown.splitlines(keepends=True):
        stripped = line.strip()
        fence = _fence_marker(stripped)
        if fence:
            if not in_fence:
                in_fence = True
                fence_marker = fence
            elif fence == fence_marker:
                in_fence = False
                fence_marker = ""
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        out.append(_rewrite_math_line(line, replace))

    return "".join(out)


def _rewrite_math_line(line: str, replace: Callable[[MathToken], str]) -> str:
    ending = ""
    if line.endswith("\r\n"):
        ending = "\r\n"
        line = line[:-2]
    elif line.endswith("\n"):
        ending = "\n"
        line = line[:-1]

    block = _whole_line_math(line)
    if block:
        return replace(block) + ending

    return _rewrite_inline_math(line, replace) + ending


def _whole_line_math(line: str) -> MathToken | None:
    stripped = line.strip()
    pairs = (("$$", "$$"), ("\\[", "\\]"))
    for start, end in pairs:
        if stripped.startswith(start) and stripped.endswith(end) and len(stripped) > len(start) + len(end):
            return MathToken(stripped[len(start) : -len(end)].strip(), True)

    if stripped.startswith("$") and stripped.endswith("$") and len(stripped) > 2:
        latex = stripped[1:-1].strip()
        if _looks_like_display_math(latex):
            return MathToken(latex, True)
    return None


def _rewrite_inline_math(line: str, replace: Callable[[MathToken], str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(line):
        if line[i] == "`":
            end = line.find("`", i + 1)
            if end == -1:
                out.append(line[i:])
                break
            out.append(line[i : end + 1])
            i = end + 1
            continue

        if line.startswith("\\(", i):
            end = line.find("\\)", i + 2)
            if end != -1:
                latex = line[i + 2 : end].strip()
                out.append(replace(MathToken(latex, False)) if latex else line[i : end + 2])
                i = end + 2
                continue

        if line[i] == "$" and not _escaped(line, i):
            end = _find_closing_dollar(line, i + 1)
            if end != -1:
                latex = line[i + 1 : end].strip()
                superscript = _superscript_marker(latex)
                if superscript is not None:
                    out.append(f"<sup>{html.escape(superscript)}</sup>")
                elif latex and _valid_inline_latex(latex):
                    out.append(replace(MathToken(latex, False)))
                else:
                    out.append(line[i : end + 1])
                i = end + 1
                continue

        out.append(line[i])
        i += 1
    return "".join(out)


def _fence_marker(stripped: str) -> str:
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return ""


def _find_closing_dollar(line: str, start: int) -> int:
    i = start
    while i < len(line):
        if line[i] == "$" and not _escaped(line, i):
            return i
        i += 1
    return -1


def _escaped(line: str, index: int) -> bool:
    count = 0
    i = index - 1
    while i >= 0 and line[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def _valid_inline_latex(latex: str) -> bool:
    if not latex:
        return False
    if "\n" in latex:
        return False
    if latex[0].isspace() or latex[-1].isspace():
        return False
    if len(latex) > 400:
        return False
    if re.fullmatch(r"[A-Za-z]", latex):
        return True
    return any(char in latex for char in "\\_^{}=+-*/<>(),") or any(char.isdigit() for char in latex)


def _superscript_marker(latex: str) -> str | None:
    match = re.fullmatch(r"\^\{?([^{}]+)\}?", latex.strip())
    return match.group(1) if match else None


def _looks_like_display_math(latex: str) -> bool:
    if len(latex) > 48:
        return True
    markers = ("\\frac", "\\sum", "\\prod", "\\int", "\\tag", "\\begin", "softmax", "Attention", "MultiHead")
    return any(marker in latex for marker in markers)


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except OSError:
        return 0, 0
