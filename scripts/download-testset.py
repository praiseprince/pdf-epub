from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "testsets" / "manifest.json"
SKIP_TYPES = {"html-pdf", "screenshot-pdf"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download direct-PDF items from testsets/manifest.json.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--ids", nargs="*", default=[], help="Optional item ids to download.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = _load_manifest(args.manifest)
    configured_output = Path(str(manifest.get("outputDirectory", "testsets/pdfs")))
    output_dir = configured_output if configured_output.is_absolute() else ROOT / configured_output
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = set(args.ids)
    items = manifest.get("items") or []
    if not isinstance(items, list):
        print("manifest items must be a list", file=sys.stderr)
        return 1

    downloaded = 0
    skipped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if selected and item_id not in selected:
            continue
        if item.get("type") in SKIP_TYPES:
            print(f"skip {item_id}: generated locally from HTML/screenshots")
            skipped += 1
            continue
        url = str(item.get("url") or "")
        filename = str(item.get("filename") or "")
        if not url or not filename:
            print(f"skip {item_id}: missing url or filename")
            skipped += 1
            continue
        target = output_dir / filename
        if target.exists() and not args.force:
            print(f"ok   {item_id}: {target.relative_to(ROOT)} exists")
            skipped += 1
            continue
        _download(url, target, timeout=args.timeout)
        print(f"get  {item_id}: {target.relative_to(ROOT)} ({target.stat().st_size:,} bytes)")
        downloaded += 1

    print(f"downloaded={downloaded} skipped={skipped}")
    return 0


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise SystemExit("manifest must be a JSON object")
    return data


def _download(url: str, target: Path, *, timeout: int) -> None:
    parsed = urllib.parse.urlsplit(url)
    safe_url = urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            urllib.parse.quote(parsed.path, safe="/%"),
            parsed.query,
            parsed.fragment,
        )
    )
    request = urllib.request.Request(safe_url, headers={"User-Agent": "pdf-epub-testset/1.0"})
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as stream:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
    if partial.stat().st_size < 4:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded file was empty: {url}")
    with partial.open("rb") as stream:
        header = stream.read(4)
    if header != b"%PDF":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download did not look like a PDF: {url}")
    partial.replace(target)


if __name__ == "__main__":
    raise SystemExit(main())
