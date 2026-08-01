from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from PIL import Image

from local_app.assets import add_page_snapshots, collect_paddle_assets, merge_bundles
from local_app.epub_builder import build_epub


ONE_PIXEL_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


def test_epub_builder_preserves_raw_html_images_and_tables(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
# Result

<div class="figure"><img src="imgs/figure-1.png" alt="Figure 1" width="100%"></div>

<table><tr><th>Symbol</th><th>Value</th></tr><tr><td>x</td><td>1</td></tr></table>
""",
                "markdownImages": {"imgs/figure-1.png": f"data:image/png;base64,{ONE_PIXEL_PNG}"},
                "outputImages": {},
            }
        ],
    }
    assets_dir = tmp_path / "assets"
    bundle = collect_paddle_assets(
        raw_result,
        assets_dir,
        max_image_bytes=1024 * 1024,
        max_total_bytes=1024 * 1024,
    )
    result = build_epub(
        output_path=tmp_path / "book.epub",
        title="Result",
        author="",
        original_filename="result.pdf",
        raw_result=raw_result,
        bundle=bundle,
        snapshot_paths=[],
        snapshot_source_dir=tmp_path / "pages",
        assets_source_dir=assets_dir,
    )

    assert result.output_path.exists()
    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        names = epub.namelist()

    assert "&lt;table" not in chapter
    assert "<table>" in chapter
    assert "Figure 1" in chapter
    assert 'width="100%"' not in chapter
    assert "../assets/" in chapter
    assert any(name.startswith("EPUB/assets/") for name in names)


def test_epub_builder_renders_math_png_and_uses_first_pdf_page_as_cover(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": (
                    "Encoder depth is $N = 6$.\n\n"
                    "$$\\mathbf{h}_{t+1}=\\mathbf{h}_{t}+f(\\mathbf{h}_{t},\\boldsymbol{\\theta}_{t})$$"
                ),
                "markdownImages": {},
                "outputImages": {},
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    cover = pages_dir / "page-01.png"
    cover.write_bytes(base64.b64decode(ONE_PIXEL_PNG))
    assets_dir = tmp_path / "assets"
    bundle = merge_bundles(add_page_snapshots([cover]))

    result = build_epub(
        output_path=tmp_path / "math.epub",
        title="Math",
        author="",
        original_filename="math.pdf",
        raw_result=raw_result,
        bundle=bundle,
        snapshot_paths=[cover],
        snapshot_source_dir=pages_dir,
        assets_source_dir=assets_dir,
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        cover_xhtml = epub.read("EPUB/text/cover.xhtml").decode("utf-8")
        names = epub.namelist()
        display_math_name = next(name for name in names if name.startswith("EPUB/assets/math/") and name.endswith(".png"))
        math_blob = epub.read(display_math_name)

    assert "$N = 6$" not in chapter
    assert "math-inline" in chapter
    assert "math-block" in chapter
    assert "math-source" not in chapter
    assert "page-snapshot" not in chapter
    assert "Cover page from source PDF" in cover_xhtml
    assert "Converted from" not in cover_xhtml
    assert "<h1>Math</h1>" not in cover_xhtml
    assert any(name.startswith("EPUB/assets/math/") and name.endswith(".png") for name in names)
    image_path = tmp_path / "display-math.png"
    image_path.write_bytes(math_blob)
    with Image.open(image_path) as image:
        assert image.width > 100
        assert image.height > 20


def test_epub_builder_keeps_unrenderable_math_as_visible_source(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": "$$\\frac{1}{$$",
                "markdownImages": {},
                "outputImages": {},
            }
        ],
    }
    assets_dir = tmp_path / "assets"
    result = build_epub(
        output_path=tmp_path / "bad-math.epub",
        title="Bad Math",
        author="",
        original_filename="bad-math.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=tmp_path / "pages",
        assets_source_dir=assets_dir,
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")

    assert "formula(s) could not be rendered" in " ".join(result.warnings)
    assert "math-source" in chapter
    assert "\\frac{1}{" in chapter


def test_epub_builder_uses_ai_repair_after_mathjax_failure(tmp_path: Path) -> None:
    class FakeRepairer:
        def repair_failed_formulas(self, failures, warnings):
            assert failures[0]["latex"] == "\\frac{1}{"
            return {failures[0]["key"]: "\\frac{1}{2}"}

    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": "$$\\frac{1}{$$",
                "markdownImages": {},
                "outputImages": {},
            }
        ],
    }
    assets_dir = tmp_path / "assets"
    result = build_epub(
        output_path=tmp_path / "ai-math.epub",
        title="AI Math",
        author="",
        original_filename="ai-math.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=tmp_path / "pages",
        assets_source_dir=assets_dir,
        math_repairer=FakeRepairer(),
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        names = epub.namelist()

    assert "rendered after AI math repair" in " ".join(result.warnings)
    assert "math-source" not in chapter
    assert "math-block" in chapter
    assert any(name.startswith("EPUB/assets/math/") and name.endswith(".png") for name in names)


def test_epub_builder_can_emit_mathml_for_kepub_path(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": (
                    "Euler update:\n\n"
                    "$$\\mathbf{h}_{t+1}=\\mathbf{h}_{t}+f(\\mathbf{h}_{t},\\boldsymbol{\\theta}_{t}) \\tag*{(1)}$$"
                ),
                "markdownImages": {},
                "outputImages": {},
            }
        ],
    }
    assets_dir = tmp_path / "assets"
    result = build_epub(
        output_path=tmp_path / "mathml.kepub.epub",
        title="MathML",
        author="",
        original_filename="math.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=tmp_path / "pages",
        assets_source_dir=assets_dir,
        math_output="mathml",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        package = epub.read("EPUB/package.opf").decode("utf-8")
        names = epub.namelist()

    assert "<math " in chapter
    assert "<img" not in chapter
    assert 'properties="mathml"' in package
    assert not any(name.startswith("EPUB/assets/math/") and name.endswith(".png") for name in names)
