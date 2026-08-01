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

from .assets import AssetBundle, normalize_asset_key
from .math_render import MathMLRenderer, MathRenderer, MathRepairer, collect_math_tokens, rewrite_math


@dataclass
class EpubBuildResult:
    output_path: Path
    warnings: list[str]


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

    fallback_to_page_images = not pages and bool(snapshot_paths)
    max_pages = max(len(pages), len(snapshot_paths) if fallback_to_page_images else 0, 1)
    chapters: list[dict[str, str]] = []
    cover_image_href = bundle.image_map.get("page:1")

    for index in range(max_pages):
        page_number = index + 1
        markdown = pages[index].get("markdownText", "") if index < len(pages) else ""
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
