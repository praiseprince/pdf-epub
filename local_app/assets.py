from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx


DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.+/]+);base64,(?P<body>.+)$", re.DOTALL)


@dataclass
class AssetBundle:
    image_map: dict[str, str] = field(default_factory=dict)
    manifest_items: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def collect_paddle_assets(
    raw_result: dict[str, Any] | None,
    assets_dir: Path,
    *,
    max_image_bytes: int,
    max_total_bytes: int,
) -> AssetBundle:
    bundle = AssetBundle()
    if not raw_result:
        return bundle

    assets_dir.mkdir(parents=True, exist_ok=True)
    seen_values: dict[str, str] = {}
    total_bytes = 0

    for page in raw_result.get("pages", []):
        if not isinstance(page, dict):
            continue
        for field_name in ("markdownImages", "outputImages"):
            mapped = page.get(field_name)
            if not isinstance(mapped, dict):
                continue
            for key, value in mapped.items():
                if not isinstance(key, str) or not isinstance(value, str) or not value:
                    continue
                if value in seen_values:
                    _remember_key(bundle.image_map, key, seen_values[value])
                    continue

                try:
                    content, mime, extension = _read_asset(value)
                except Exception as exc:
                    bundle.warnings.append(f"Could not read OCR image {key}: {exc}")
                    continue

                if len(content) > max_image_bytes:
                    bundle.warnings.append(f"Skipped OCR image {key}: image exceeds configured size guardrail.")
                    continue
                if total_bytes + len(content) > max_total_bytes:
                    bundle.warnings.append("Skipped remaining OCR images: total asset guardrail reached.")
                    continue

                digest = hashlib.sha256(content).hexdigest()[:20]
                filename = f"{digest}.{extension}"
                target = assets_dir / filename
                if not target.exists():
                    target.write_bytes(content)

                href = f"assets/{filename}"
                total_bytes += len(content)
                seen_values[value] = href
                bundle.manifest_items[href] = mime
                _remember_key(bundle.image_map, key, href)

    return bundle


def add_page_snapshots(snapshot_paths: list[Path]) -> AssetBundle:
    bundle = AssetBundle()
    for index, path in enumerate(snapshot_paths, start=1):
        href = f"pages/{path.name}"
        bundle.image_map[f"page:{index}"] = href
        bundle.manifest_items[href] = "image/png"
    return bundle


def merge_bundles(*bundles: AssetBundle) -> AssetBundle:
    out = AssetBundle()
    for bundle in bundles:
        out.image_map.update(bundle.image_map)
        out.manifest_items.update(bundle.manifest_items)
        out.warnings.extend(bundle.warnings)
    return out


def normalize_asset_key(value: str) -> list[str]:
    raw = unquote(value.strip())
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw
    path = path.replace("\\", "/").lstrip("./")
    keys = [raw, path]
    if path.startswith("/"):
        keys.append(path.lstrip("/"))
    basename = Path(path).name
    if basename:
        keys.append(basename)
    return list(dict.fromkeys(key for key in keys if key))


def _remember_key(image_map: dict[str, str], key: str, href: str) -> None:
    for normalized in normalize_asset_key(key):
        image_map[normalized] = href


def _read_asset(value: str) -> tuple[bytes, str, str]:
    data_url = DATA_URL_RE.match(value)
    if data_url:
        mime = data_url.group("mime")
        content = base64.b64decode(data_url.group("body"), validate=False)
        return content, mime, _extension_for(mime, value)

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(value)
            response.raise_for_status()
            content = response.content
            header_mime = response.headers.get("content-type", "").split(";", 1)[0]
            detected_mime = _mime_from_bytes(content)
            mime = header_mime if header_mime.startswith("image/") else detected_mime
            return content, mime, _extension_for(mime, parsed.path)

    path = Path(value)
    if path.exists():
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or _mime_from_bytes(content)
        return content, mime, _extension_for(mime, path.name)

    try:
        content = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("asset value is not a URL, file path, data URL, or base64 blob") from exc
    mime = _mime_from_bytes(content)
    return content, mime, _extension_for(mime, "")


def _mime_from_bytes(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return "image/webp"
    return "application/octet-stream"


def _extension_for(mime: str, fallback_name: str) -> str:
    fallback = Path(fallback_name).suffix.lower().lstrip(".")
    if fallback in {"png", "jpg", "jpeg", "gif", "svg", "webp"}:
        return "jpg" if fallback == "jpeg" else fallback
    if mime == "image/png":
        return "png"
    if mime == "image/jpeg":
        return "jpg"
    if mime == "image/gif":
        return "gif"
    if mime == "image/svg+xml":
        return "svg"
    if mime == "image/webp":
        return "webp"
    return "bin"
