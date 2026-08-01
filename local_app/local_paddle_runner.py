from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


EVENT_PREFIX = "__LOCAL_OCR_EVENT__"


def main() -> int:
    payload = _read_payload()
    images = payload.get("images")
    checkpoint_raw = str(payload.get("checkpointDir") or "")
    pipeline_version = str(payload.get("pipelineVersion") or "v1.6")
    device = str(payload.get("device") or "cpu")

    if not isinstance(images, list) or not images:
        _event({"event": "error", "message": "No page images were provided."})
        return 2
    if not checkpoint_raw:
        _event({"event": "error", "message": "checkpointDir is required."})
        return 2

    checkpoint_dir = Path(checkpoint_raw)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    try:
        from paddleocr import PaddleOCRVL
    except Exception as exc:
        _event({"event": "error", "message": f"Could not import PaddleOCRVL: {exc}"})
        return 2

    _event({"event": "model_loading", "pipelineVersion": pipeline_version, "device": device})
    started = time.monotonic()
    try:
        pipeline = PaddleOCRVL(pipeline_version=pipeline_version, device=device)
    except TypeError:
        pipeline = PaddleOCRVL(pipeline_version=pipeline_version)
    except Exception as exc:
        _event({"event": "error", "message": f"Could not initialize PaddleOCRVL: {exc}"})
        return 2
    _event({"event": "model_ready", "elapsedSeconds": round(time.monotonic() - started, 3)})

    for image in images:
        page = int(image["page"])
        path = Path(str(image["path"]))
        checkpoint_path = checkpoint_dir / f"page-{page:04d}.json"
        if checkpoint_path.exists():
            _event({"event": "page_done", "page": page, "checkpoint": str(checkpoint_path), "cached": True})
            continue

        _event({"event": "page_start", "page": page, "path": str(path)})
        page_started = time.monotonic()
        try:
            results = list(
                pipeline.predict(
                    str(path),
                    use_chart_recognition=False,
                    use_seal_recognition=False,
                    use_ocr_for_image_block=False,
                )
            )
            page_result = _normalize_page_result(results[0] if results else None, page=page)
            checkpoint_path.write_text(json.dumps(page_result, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            _event({"event": "page_error", "page": page, "message": str(exc)})
            return 1

        _event(
            {
                "event": "page_done",
                "page": page,
                "checkpoint": str(checkpoint_path),
                "elapsedSeconds": round(time.monotonic() - page_started, 3),
                "cached": False,
            }
        )

    _event({"event": "done"})
    return 0


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return data


def _normalize_page_result(result: Any, *, page: int) -> dict[str, Any]:
    if result is None:
        return _empty_page()

    markdown = getattr(result, "markdown", None)
    if not isinstance(markdown, dict):
        markdown = {}

    text = _markdown_text(markdown)
    markdown_images = markdown.get("markdown_images") or markdown.get("markdownImages") or {}
    if not isinstance(markdown_images, dict):
        markdown_images = {}

    result_json = getattr(result, "json", None)
    if not isinstance(result_json, dict):
        result_json = {}
    pruned = result_json.get("res") if isinstance(result_json.get("res"), dict) else {}

    page_result = {
        "markdownText": text,
        "markdownImages": markdown_images,
        "outputImages": _dict_or_empty(pruned.get("outputImages")),
        "prunedResult": _pruned_result(pruned),
    }
    page_result["prunedResult"]["page_index"] = page - 1
    return page_result


def _markdown_text(markdown: dict[str, Any]) -> str:
    value = markdown.get("markdown_texts")
    if isinstance(value, list):
        return "\n\n".join(str(item) for item in value if str(item).strip()).strip()
    if isinstance(value, str):
        return value.strip()
    value = markdown.get("text")
    return str(value).strip() if value is not None else ""


def _pruned_result(value: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "width",
        "height",
        "model_settings",
        "parsing_res_list",
        "layout_det_res",
        "page_index",
        "page_count",
    }
    return {key: _jsonable(inner) for key, inner in value.items() if key in keep}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(inner) for key, inner in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(inner) for inner in value]
        return str(value)


def _empty_page() -> dict[str, Any]:
    return {"markdownText": "", "markdownImages": {}, "outputImages": {}, "prunedResult": {}}


def _event(payload: dict[str, Any]) -> None:
    print(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
