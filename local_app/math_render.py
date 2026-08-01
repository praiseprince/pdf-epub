from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .assets import AssetBundle


@dataclass(frozen=True)
class MathToken:
    latex: str
    display: bool


class MathRenderer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.helper_path = Path(__file__).parent / "node" / "math_render.mjs"
        self.cache: dict[MathToken, str] = {}

    def render_many(self, tokens: Iterable[MathToken], warnings: list[str]) -> AssetBundle:
        unique_tokens = list(dict.fromkeys(token for token in tokens if token.latex.strip()))
        bundle = AssetBundle()
        pending = []

        for token in unique_tokens:
            filename = f"{self._key(token)}.png"
            href = f"assets/math/{filename}"
            self.cache[token] = href
            bundle.image_map[f"math:{self._key(token)}"] = href
            bundle.manifest_items[href] = "image/png"
            target = self.output_dir / filename
            if not target.exists():
                pending.append(
                    {
                        "key": self._key(token),
                        "latex": token.latex,
                        "display": token.display,
                        "filename": filename,
                    }
                )

        if not pending:
            return bundle

        self.output_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["node", str(self.helper_path)],
            input=json.dumps({"outputDir": str(self.output_dir), "formulas": pending}),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            warnings.append(proc.stderr.strip() or "Formula rendering failed.")
            for item in pending:
                token = MathToken(str(item["latex"]), bool(item["display"]))
                self.cache.pop(token, None)
                bundle.manifest_items.pop(f"assets/math/{item['filename']}", None)
            return bundle

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            warnings.append("Formula renderer returned invalid JSON.")
            return bundle

        failures = [item for item in result.get("results", []) if not item.get("ok")]
        if failures:
            warnings.append(f"{len(failures)} formula(s) could not be rendered.")
            failed_keys = {str(item.get("key")) for item in failures}
            for token in unique_tokens:
                key = self._key(token)
                if key in failed_keys:
                    self.cache.pop(token, None)
                    bundle.image_map.pop(f"math:{key}", None)
                    bundle.manifest_items.pop(f"assets/math/{key}.png", None)
        repairs = [item for item in result.get("results", []) if item.get("ok") and item.get("repaired")]
        if repairs:
            warnings.append(f"{len(repairs)} formula(s) rendered after local syntax repair.")

        return bundle

    def html_for(self, token: MathToken) -> str:
        href = self.cache.get(token)
        alt = html.escape(token.latex, quote=True)
        if not href:
            if token.display:
                return f'<pre class="math-source" role="math">{alt}</pre>'
            return f'<span class="math-source" role="math">{alt}</span>'
        if token.display:
            return f'<div class="math-block"><img class="math-display" src="../{href}" alt="{alt}" /></div>'
        return f'<img class="math-inline" src="../{href}" alt="{alt}" />'

    def _key(self, token: MathToken) -> str:
        payload = f"{'display' if token.display else 'inline'}\0{token.latex}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]


def collect_math_tokens(markdown_pages: Iterable[str]) -> list[MathToken]:
    tokens: list[MathToken] = []
    for markdown in markdown_pages:
        rewrite_math(markdown, lambda token: tokens.append(token) or "")
    return tokens


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
