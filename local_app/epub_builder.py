from __future__ import annotations

import html
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import bleach
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from PIL import Image

from .assets import AssetBundle, normalize_asset_key
from .math_render import MathMLRenderer, MathRenderer, MathRepairer, collect_math_tokens, rewrite_math


@dataclass
class EpubBuildResult:
    output_path: Path
    warnings: list[str]


@dataclass
class FigureCropCandidate:
    bbox: tuple[float, float, float, float]
    caption_text: str


@dataclass
class PreservedFigure:
    href: str
    alt: str
    caption_text: str


BOOK_CSS = """
body {
  font-family: serif;
  line-height: 1.55;
  margin: 0.8em;
  text-align: left;
}
p { margin: 0 0 0.85em; }
h1, h2, h3, h4, h5, h6 { line-height: 1.2; margin: 1.1em 0 0.55em; }
a { color: inherit; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; }
figure { margin: 1em 0; page-break-inside: avoid; break-inside: avoid; }
figcaption { font-size: 0.9em; line-height: 1.35; margin-top: 0.4em; }
.preserved-figure img { width: 100%; max-width: 100%; }
.page-snapshot { margin: 0 0 1.2em; }
.page-snapshot img { width: 100%; max-width: 100%; }
.ocr-text { border-top: 1px solid #aaa; margin-top: 1em; padding-top: 0.8em; }
.math-inline { display: inline-block; margin: 0 0.08em; vertical-align: -0.32em; max-height: 1.75em; width: auto; }
.math-block { text-align: center; margin: 1.05em 0; page-break-inside: avoid; break-inside: avoid; }
.math-display { background: #fff; display: block; height: auto; margin: 0.4em auto; max-width: 100%; }
.mathml-inline math { display: inline; }
.mathml-block math { display: block; margin: 0.45em auto; max-width: 100%; }
.math-source { font-family: serif; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; max-width: 100%; margin: 1em 0; font-size: 0.92em; }
th, td { border: 1px solid #999; padding: 0.3em 0.45em; vertical-align: top; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 0.75em; border: 1px solid #aaa; }
code { font-family: monospace; }
blockquote { margin: 1em 1.2em; }
""".strip()


ALLOWED_TAGS = {
    "a",
    "abbr",
    "blockquote",
    "br",
    "caption",
    "code",
    "del",
    "div",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "li",
    "maligngroup",
    "malignmark",
    "math",
    "menclose",
    "merror",
    "mfenced",
    "mfrac",
    "mglyph",
    "mi",
    "mlabeledtr",
    "mmultiscripts",
    "mn",
    "mo",
    "mover",
    "mpadded",
    "mprescripts",
    "mroot",
    "mrow",
    "ms",
    "mspace",
    "msqrt",
    "mstyle",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
    "none",
    "ol",
    "p",
    "pre",
    "section",
    "semantics",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}

MATHML_ATTRIBUTES = [
    "accent",
    "accentunder",
    "align",
    "alttext",
    "bevelled",
    "class",
    "close",
    "columnalign",
    "columnlines",
    "columnspacing",
    "columnspan",
    "data-mjx-texclass",
    "denomalign",
    "depth",
    "dir",
    "display",
    "displaystyle",
    "encoding",
    "fence",
    "form",
    "height",
    "href",
    "id",
    "largeop",
    "linethickness",
    "lspace",
    "mathbackground",
    "mathcolor",
    "mathsize",
    "mathvariant",
    "maxsize",
    "minsize",
    "movablelimits",
    "notation",
    "numalign",
    "open",
    "rowalign",
    "rowlines",
    "rowspacing",
    "rowspan",
    "rspace",
    "scriptlevel",
    "scriptminsize",
    "scriptsizemultiplier",
    "selection",
    "separator",
    "separators",
    "stretchy",
    "subscriptshift",
    "supscriptshift",
    "symmetric",
    "title",
    "width",
    "xmlns",
]

ALLOWED_ATTRIBUTES = {
    "*": MATHML_ATTRIBUTES,
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
}

MD = MarkdownIt("commonmark", {"html": True, "linkify": False, "typographer": False}).enable("table")


def build_epub(
    *,
    output_path: Path,
    title: str,
    author: str,
    original_filename: str,
    raw_result: dict[str, Any] | None,
    bundle: AssetBundle,
    snapshot_paths: list[Path],
    snapshot_source_dir: Path,
    assets_source_dir: Path,
    math_repairer: MathRepairer | None = None,
    math_output: Literal["png", "mathml"] = "png",
) -> EpubBuildResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    warnings = list(bundle.warnings)
    title = _clean_text(title) or _clean_text(Path(original_filename).stem) or "Untitled document"
    author = _clean_text(author)

    pages = _result_pages(raw_result)
    markdown_pages = [str(page.get("markdownText", "")) for page in pages]
    math_renderer = (
        MathMLRenderer(repairer=math_repairer)
        if math_output == "mathml"
        else MathRenderer(assets_source_dir / "math", repairer=math_repairer)
    )
    math_bundle = math_renderer.render_many(collect_math_tokens(markdown_pages), warnings)
    bundle.image_map.update(math_bundle.image_map)
    bundle.manifest_items.update(math_bundle.manifest_items)
    bundle.warnings.extend(math_bundle.warnings)
    preserved_figures = _collect_preserved_figures(
        pages,
        snapshot_source_dir=snapshot_source_dir,
        assets_source_dir=assets_source_dir,
        bundle=bundle,
        warnings=warnings,
    )

    fallback_to_page_images = not pages and bool(snapshot_paths)
    max_pages = max(len(pages), len(snapshot_paths) if fallback_to_page_images else 0, 1)
    chapters: list[dict[str, str]] = []
    cover_image_href = bundle.image_map.get("page:1")

    for index in range(max_pages):
        page_number = index + 1
        markdown = pages[index].get("markdownText", "") if index < len(pages) else ""
        markdown = _inject_preserved_figures(markdown, preserved_figures.get(page_number, []))
        body_parts = [f'<section class="page" id="page-{page_number}">', f"<h2>Page {page_number}</h2>"]

        snapshot_href = bundle.image_map.get(f"page:{page_number}")
        if fallback_to_page_images and snapshot_href:
            body_parts.append(
                '<figure class="page-snapshot">'
                f'<img src="../{_xml_attr(snapshot_href)}" alt="Original page {page_number}" />'
                "</figure>"
            )

        rendered = render_markdown_fragment(markdown, bundle.image_map, math_renderer, warnings)
        if rendered:
            body_parts.append(f'<section class="ocr-text">{rendered}</section>')
        elif not snapshot_href:
            body_parts.append("<p>No recognized content was returned for this page.</p>")

        body_parts.append("</section>")
        filename = f"text/page-{page_number:04d}.xhtml"
        content = xhtml_document(f"{title} - Page {page_number}", "\n".join(body_parts))
        chapters.append(
            {
                "id": f"page-{page_number}",
                "title": f"Page {page_number}",
                "filename": filename,
                "content": content,
                "properties": "mathml" if "<math " in content else "",
            }
        )

    entries: list[tuple[str, bytes | str, int]] = [
        ("mimetype", "application/epub+zip", zipfile.ZIP_STORED),
        ("META-INF/container.xml", container_xml(), zipfile.ZIP_DEFLATED),
        (
            "EPUB/package.opf",
            package_document(title, author, original_filename, chapters, bundle, cover_image_href),
            zipfile.ZIP_DEFLATED,
        ),
        ("EPUB/nav.xhtml", nav_document(title, chapters), zipfile.ZIP_DEFLATED),
        ("EPUB/styles/book.css", BOOK_CSS, zipfile.ZIP_DEFLATED),
        (
            "EPUB/text/cover.xhtml",
            cover_document(title, author, original_filename, warnings, cover_image_href),
            zipfile.ZIP_DEFLATED,
        ),
    ]

    for chapter in chapters:
        entries.append((f"EPUB/{chapter['filename']}", chapter["content"], zipfile.ZIP_DEFLATED))

    for snapshot in snapshot_paths:
        entries.append((f"EPUB/pages/{snapshot.name}", snapshot.read_bytes(), zipfile.ZIP_DEFLATED))

    for href in sorted(bundle.manifest_items):
        if not href.startswith("assets/"):
            continue
        asset_path = assets_source_dir / Path(href).relative_to("assets")
        if asset_path.exists():
            entries.append((f"EPUB/{href}", asset_path.read_bytes(), zipfile.ZIP_DEFLATED))
        else:
            warnings.append(f"Missing asset {href} while building EPUB.")

    with zipfile.ZipFile(output_path, "w") as epub:
        for path, content, compression in entries:
            data = content.encode("utf-8") if isinstance(content, str) else content
            epub.writestr(path, data, compress_type=compression)

    return EpubBuildResult(output_path=output_path, warnings=warnings)


def render_markdown_fragment(
    markdown: str,
    image_map: dict[str, str],
    math_renderer: MathRenderer,
    warnings: list[str],
) -> str:
    if not markdown.strip():
        return ""

    prepared = rewrite_math(markdown, math_renderer.html_for)
    prepared = _rewrite_markdown_image_refs(prepared, image_map)
    rendered = MD.render(prepared)
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    soup = BeautifulSoup(cleaned, "html.parser")

    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        if src.startswith("../assets/") or src.startswith("../pages/"):
            if not img.get("alt"):
                img["alt"] = "Document image"
            continue
        href = _resolve_image_href(src, image_map)
        if href:
            img["src"] = f"../{href}"
            if not img.get("alt"):
                img["alt"] = "Document image"
        else:
            alt = img.get("alt") or "Missing document image"
            replacement = soup.new_tag("span")
            replacement["class"] = "image-fallback"
            replacement.string = str(alt)
            img.replace_with(replacement)
            warnings.append(f"Could not resolve OCR image reference: {src}")

    for tag in soup.find_all(True):
        tag.attrs = {key: value for key, value in tag.attrs.items() if _safe_attr(tag.name, key, value)}

    fragment = "".join(str(child) for child in soup.contents)
    return _xhtml_void_tags(fragment)


def xhtml_document(title: str, body: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_xml(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/book.css" />
</head>
<body>
{body}
</body>
</html>"""


def cover_document(
    title: str,
    author: str,
    original_filename: str,
    warnings: list[str],
    cover_image_href: str | None,
) -> str:
    if cover_image_href:
        return xhtml_document(
            title,
            f"""<section epub:type="cover" class="cover-page">
  <figure class="cover-image"><img src="../{_xml_attr(cover_image_href)}" alt="Cover page from source PDF" /></figure>
</section>""",
        )

    warning_items = "".join(f"<li>{_xml(warning)}</li>" for warning in warnings[:20])
    warning_block = f"<section><h2>Conversion notes</h2><ul>{warning_items}</ul></section>" if warning_items else ""
    return xhtml_document(
        title,
        f"""<section epub:type="cover">
  <h1>{_xml(title)}</h1>
  {f'<p>{_xml(author)}</p>' if author else ''}
  <p>Converted from {_xml(original_filename)}</p>
</section>
{warning_block}""",
    )


def nav_document(title: str, chapters: list[dict[str, str]]) -> str:
    items = "\n".join(
        f'<li><a href="{_xml_attr(chapter["filename"])}">{_xml(chapter["title"])}</a></li>' for chapter in chapters
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head><meta charset="utf-8" /><title>Contents</title></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>{_xml(title)}</h1>
  <ol>{items}</ol>
</nav>
</body>
</html>"""


def package_document(
    title: str,
    author: str,
    original_filename: str,
    chapters: list[dict[str, str]],
    bundle: AssetBundle,
    cover_image_href: str | None,
) -> str:
    modified = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    identifier = f"urn:uuid:{uuid.uuid4()}"
    chapter_items = "\n".join(
        (
            f'<item id="{_xml_attr(chapter["id"])}" href="{_xml_attr(chapter["filename"])}" '
            f'media-type="application/xhtml+xml"{_manifest_properties(chapter.get("properties", ""))} />'
        )
        for chapter in chapters
    )
    spine = "\n".join(f'<itemref idref="{_xml_attr(chapter["id"])}" />' for chapter in chapters)
    resources = []
    for index, (href, mime) in enumerate(sorted(bundle.manifest_items.items()), start=1):
        if href == cover_image_href:
            resources.append(
                f'<item id="cover-image" href="{_xml_attr(href)}" media-type="{_xml_attr(mime)}" properties="cover-image" />'
            )
        else:
            resources.append(f'<item id="res-{index}" href="{_xml_attr(href)}" media-type="{_xml_attr(mime)}" />')
    resource_items = "\n".join(resources)
    cover_meta = '<meta name="cover" content="cover-image" />' if cover_image_href else ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{_xml(identifier)}</dc:identifier>
    <dc:title>{_xml(title)}</dc:title>
    {f'<dc:creator>{_xml(author)}</dc:creator>' if author else ''}
    <dc:language>en</dc:language>
    <dc:source>{_xml(original_filename)}</dc:source>
    {cover_meta}
    <meta property="dcterms:modified">{_xml(modified)}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="css" href="styles/book.css" media-type="text/css" />
    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml" />
    {chapter_items}
    {resource_items}
  </manifest>
  <spine>
    <itemref idref="cover" />
    {spine}
  </spine>
</package>"""


def container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>"""


def _result_pages(raw_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw_result:
        return []
    pages = raw_result.get("pages", [])
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def figure_crop_page_numbers(raw_result: dict[str, Any] | None) -> set[int]:
    return {
        page_number
        for page_number, page in enumerate(_result_pages(raw_result), start=1)
        if _figure_crop_candidates(page)
    }


def _collect_preserved_figures(
    pages: list[dict[str, Any]],
    *,
    snapshot_source_dir: Path,
    assets_source_dir: Path,
    bundle: AssetBundle,
    warnings: list[str],
) -> dict[int, list[PreservedFigure]]:
    figures_by_page: dict[int, list[PreservedFigure]] = {}
    figure_dir = assets_source_dir / "figure-crops"

    for page_number, page in enumerate(pages, start=1):
        candidates = _figure_crop_candidates(page)
        if not candidates:
            continue

        page_image_path = _page_image_path(snapshot_source_dir, page_number)
        if page_image_path is None:
            warnings.append(f"Could not preserve figure crop(s) on page {page_number}: rendered page image is missing.")
            continue

        try:
            with Image.open(page_image_path) as image:
                image = image.convert("RGB")
                pruned = _pruned_result(page)
                raw_width = _positive_number(pruned.get("width"), image.width)
                raw_height = _positive_number(pruned.get("height"), image.height)
                scale_x = image.width / raw_width
                scale_y = image.height / raw_height

                for figure_index, candidate in enumerate(candidates, start=1):
                    crop_box = _scaled_crop_box(candidate.bbox, scale_x, scale_y, image.width, image.height)
                    if crop_box is None:
                        continue
                    crop = image.crop(crop_box)
                    if crop.width < 32 or crop.height < 32:
                        continue

                    figure_dir.mkdir(parents=True, exist_ok=True)
                    target = figure_dir / f"page-{page_number:04d}-figure-{figure_index:02d}.png"
                    if not target.exists():
                        crop.save(target, "PNG", optimize=True)

                    href = f"assets/figure-crops/{target.name}"
                    bundle.manifest_items[href] = "image/png"
                    bundle.image_map[href] = href
                    figures_by_page.setdefault(page_number, []).append(
                        PreservedFigure(
                            href=href,
                            alt=_figure_alt(candidate.caption_text, page_number, figure_index),
                            caption_text=candidate.caption_text,
                        )
                    )
        except Exception as exc:
            warnings.append(f"Could not preserve figure crop(s) on page {page_number}: {exc}")

    return figures_by_page


def _figure_crop_candidates(page: dict[str, Any]) -> list[FigureCropCandidate]:
    items = _layout_items(page)
    if not items:
        return []

    pruned = _pruned_result(page)
    page_width = _positive_number(pruned.get("width"), 1200)
    page_height = _positive_number(pruned.get("height"), 1600)
    max_gap = max(90.0, page_height * 0.14)
    used_visuals: set[int] = set()
    candidates: list[FigureCropCandidate] = []

    for caption_index, caption in enumerate(items):
        if caption["label"] not in {"figure_title", "figure_caption"}:
            continue
        caption_text = caption["text"]
        caption_bbox = caption["bbox"]
        if not caption_text or not caption_bbox:
            continue
        if not _is_figure_caption_text(caption_text):
            continue

        visual_blocks: list[tuple[float, float, float, float]] = []
        visual_indices: list[int] = []
        for visual_index, item in enumerate(items):
            if visual_index in used_visuals or visual_index == caption_index:
                continue
            if item["label"] not in {"chart", "image", "figure"}:
                continue
            bbox = item["bbox"]
            if not bbox or not _is_visual_for_caption(bbox, caption_bbox, max_gap):
                continue
            visual_blocks.append(bbox)
            visual_indices.append(visual_index)

        if not visual_blocks:
            continue
        crop_bbox = _expanded_visual_crop(
            visual_blocks,
            caption_bbox=caption_bbox,
            neighbor_blocks=[
                item["bbox"]
                for neighbor_index, item in enumerate(items)
                if neighbor_index not in visual_indices
                and neighbor_index != caption_index
                and item["bbox"]
                and item["label"] not in {"figure_title", "figure_caption"}
            ],
            page_width=page_width,
            page_height=page_height,
        )
        if crop_bbox is None:
            continue
        used_visuals.update(visual_indices)
        candidates.append(FigureCropCandidate(bbox=crop_bbox, caption_text=caption_text))

    return candidates


def _is_figure_caption_text(value: str) -> bool:
    return bool(re.match(r"(?i)^\s*fig(?:ure)?\.?\s*\d+", _clean_text(value)))


def _layout_items(page: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = _pruned_result(page).get("parsing_res_list")
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("block_label") or item.get("label") or item.get("type") or item.get("block_type") or "")
        bbox = _bbox_tuple(item.get("block_bbox") or item.get("bbox") or item.get("coordinates"))
        text = _clean_text(str(item.get("block_content") or item.get("content") or item.get("text") or ""))
        items.append({"label": label, "bbox": bbox, "text": text})
    return items


def _is_visual_for_caption(
    bbox: tuple[float, float, float, float],
    caption_bbox: tuple[float, float, float, float],
    max_gap: float,
) -> bool:
    x1, y1, x2, y2 = bbox
    cx1, cy1, cx2, _cy2 = caption_bbox
    gap = cy1 - y2
    if gap < -12 or gap > max_gap:
        return False

    overlap = max(0.0, min(x2, cx2) - max(x1, cx1))
    min_width = max(1.0, min(x2 - x1, cx2 - cx1))
    if overlap / min_width >= 0.15:
        return True

    center_distance = abs(((x1 + x2) / 2.0) - ((cx1 + cx2) / 2.0))
    return center_distance <= max(x2 - x1, cx2 - cx1) * 0.75


def _inject_preserved_figures(markdown: str, figures: list[PreservedFigure]) -> str:
    if not markdown.strip() or not figures:
        return markdown

    updated = markdown
    for figure in figures:
        anchor = _caption_anchor(figure.caption_text)
        if not anchor:
            continue
        anchor_index = updated.find(anchor)
        if anchor_index < 0:
            continue

        index = _caption_container_start(updated, anchor_index)
        before = updated[:index]

        stripped_before, removed_tables = _strip_trailing_tables(before)
        if not removed_tables and re.search(r"<img\b|!\[[^\]]*\]\(", before[-1400:], flags=re.IGNORECASE):
            continue
        image_html = (
            f'\n\n<figure class="preserved-figure">'
            f'<img src="../{_xml_attr(figure.href)}" alt="{_xml_attr(figure.alt)}" />'
            "</figure>\n\n"
        )
        updated = stripped_before.rstrip() + image_html + updated[index:]

    return updated


def _strip_trailing_tables(markdown_prefix: str) -> tuple[str, int]:
    pattern = re.compile(r"(?P<tables>(?:\s*<table\b[^>]*>.*?</table>\s*)+)$", flags=re.IGNORECASE | re.DOTALL)
    match = pattern.search(markdown_prefix.rstrip())
    if not match:
        return markdown_prefix, 0
    return markdown_prefix[: match.start("tables")], len(re.findall(r"<table\b", match.group("tables"), re.IGNORECASE))


def _caption_anchor(caption_text: str) -> str:
    caption = _clean_text(caption_text)
    if not caption:
        return ""
    return caption[: min(len(caption), 80)]


def _caption_container_start(markdown: str, anchor_index: int) -> int:
    before = markdown[:anchor_index]
    last_lt = before.rfind("<")
    last_gt = before.rfind(">")
    if last_lt >= 0 and last_gt > last_lt and anchor_index - last_gt <= 3:
        tag = before[last_lt : last_gt + 1]
        if re.match(r"</?(?:div|p|center|figcaption)\b", tag, flags=re.IGNORECASE):
            return last_lt
    return anchor_index


def _figure_alt(caption_text: str, page_number: int, figure_index: int) -> str:
    caption = _clean_text(caption_text)
    match = re.match(r"(?i)(figure\s+\d+[A-Za-z]?)", caption)
    if match:
        return f"{match.group(1)} diagram"
    return f"Preserved figure {figure_index} from page {page_number}"


def _page_image_path(directory: Path, page_number: int) -> Path | None:
    for candidate in (directory / f"page-{page_number:02d}.png", directory / f"page-{page_number}.png"):
        if candidate.exists():
            return candidate
    for candidate in sorted(directory.glob("page-*.png")):
        match = re.search(r"-(\d+)\.png$", candidate.name)
        if match and int(match.group(1)) == page_number:
            return candidate
    return None


def _scaled_crop_box(
    bbox: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = bbox
    left = max(0, int(x1 * scale_x))
    upper = max(0, int(y1 * scale_y))
    right = min(width, int(x2 * scale_x + 0.999))
    lower = min(height, int(y2 * scale_y + 0.999))
    if right <= left or lower <= upper:
        return None
    return (left, upper, right, lower)


def _expanded_visual_crop(
    blocks: list[tuple[float, float, float, float]],
    *,
    caption_bbox: tuple[float, float, float, float],
    neighbor_blocks: list[tuple[float, float, float, float]],
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    x1 = min(block[0] for block in blocks)
    y1 = min(block[1] for block in blocks)
    x2 = max(block[2] for block in blocks)
    y2 = max(block[3] for block in blocks)
    margin_x = max(10.0, page_width * 0.025)
    margin_y = max(10.0, page_height * 0.018)
    caption_keepout = max(4.0, page_height * 0.017)

    left = max(0.0, x1 - margin_x)
    upper = max(0.0, y1 - margin_y)
    right = min(page_width, x2 + margin_x)
    lower = min(page_height, y2 + margin_y)

    caption_x1, caption_y1, caption_x2, _caption_y2 = caption_bbox
    horizontal_overlap = max(0.0, min(right, caption_x2) - max(left, caption_x1))
    if caption_y1 >= y1 and horizontal_overlap > 0:
        lower = min(lower, max(upper, caption_y1 - caption_keepout))

    neighbor_keepout = max(4.0, page_width * 0.004)
    vertical_keepout = max(4.0, page_height * 0.005)
    for neighbor in neighbor_blocks:
        nx1, ny1, nx2, ny2 = neighbor
        if _vertical_overlap_ratio((x1, upper, x2, lower), neighbor) < 0.1:
            if _horizontal_overlap_ratio((left, y1, right, y2), neighbor) < 0.1:
                continue
            if upper < ny2 <= y1:
                upper = min(y1, max(upper, ny2 + vertical_keepout))
            elif y2 <= ny1 < lower:
                lower = max(y2, min(lower, ny1 - vertical_keepout))
            continue
        if left < nx2 <= x1:
            left = min(x1, max(left, nx2 + neighbor_keepout))
        elif x2 <= nx1 < right:
            right = max(x2, min(right, nx1 - neighbor_keepout))

    width = right - left
    height = lower - upper
    page_area = max(1.0, page_width * page_height)
    crop_area = max(0.0, width * height)
    if width < page_width * 0.16 or height < page_height * 0.045:
        return None
    if crop_area > page_area * 0.65:
        return None
    return (left, upper, right, lower)


def _vertical_overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    _x1, y1, _x2, y2 = first
    _sx1, sy1, _sx2, sy2 = second
    overlap = max(0.0, min(y2, sy2) - max(y1, sy1))
    shortest = max(1.0, min(y2 - y1, sy2 - sy1))
    return overlap / shortest


def _horizontal_overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x1, _y1, x2, _y2 = first
    sx1, _sy1, sx2, _sy2 = second
    overlap = max(0.0, min(x2, sx2) - max(x1, sx1))
    shortest = max(1.0, min(x2 - x1, sx2 - sx1))
    return overlap / shortest


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _positive_number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _pruned_result(page: dict[str, Any]) -> dict[str, Any]:
    value = page.get("prunedResult")
    return value if isinstance(value, dict) else {}


def _rewrite_markdown_image_refs(markdown: str, image_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        alt = match.group(1)
        url = match.group(2).strip()
        href = _resolve_image_href(url, image_map)
        if not href:
            return match.group(0)
        return f"![{alt}](../{href})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace, markdown)


def _resolve_image_href(src: str, image_map: dict[str, str]) -> str | None:
    if src.startswith("../"):
        src = src[3:]
    for key in normalize_asset_key(src):
        if key in image_map:
            return image_map[key]
    return None


def _safe_attr(tag: str, key: str, value: Any) -> bool:
    if key == "href":
        return isinstance(value, str) and (value.startswith(("http://", "https://", "mailto:")) or value.startswith("#"))
    if key == "src":
        return tag == "img" and isinstance(value, str) and value.startswith("../")
    if key in {"width", "height"}:
        return isinstance(value, str) and value.isdigit()
    return True


def _xhtml_void_tags(fragment: str) -> str:
    for tag in ("br", "hr", "img"):
        fragment = re.sub(rf"<{tag}([^>/]*)>", rf"<{tag}\1 />", fragment)
    return fragment


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _xml(value: str) -> str:
    return html.escape(value, quote=False)


def _xml_attr(value: str) -> str:
    return html.escape(value, quote=True)


def _manifest_properties(value: str) -> str:
    cleaned = " ".join(part for part in value.split() if re.fullmatch(r"[A-Za-z0-9_-]+", part))
    return f' properties="{_xml_attr(cleaned)}"' if cleaned else ""


def write_raw_result(path: Path, raw_result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw_result, indent=2, ensure_ascii=False), encoding="utf-8")


def read_raw_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
