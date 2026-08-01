from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from PIL import Image

from local_app.assets import add_page_snapshots, collect_paddle_assets, merge_bundles
from local_app.epub_builder import _remove_page_header_from_crop, _trim_outer_whitespace, build_epub


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


def test_epub_builder_restores_separate_formula_number_tags(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
The third integral is:

$$ \\frac{dL}{d\\theta}=-\\int_{t_1}^{t_0} a(t)\\frac{\\partial f}{\\partial\\theta}dt $$
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 1200,
                    "height": 1600,
                    "parsing_res_list": [
                        {
                            "block_label": "display_formula",
                            "block_bbox": [250, 400, 900, 460],
                            "block_content": " $$ \\frac{dL}{d\\theta}=-\\int_{t_1}^{t_0} a(t)\\frac{\\partial f}{\\partial\\theta}dt $$ ",
                        },
                        {
                            "block_label": "formula_number",
                            "block_bbox": [1040, 415, 1070, 440],
                            "block_content": "(5)",
                        },
                    ],
                },
            }
        ],
    }

    result = build_epub(
        output_path=tmp_path / "numbered-math.epub",
        title="Numbered Math",
        author="",
        original_filename="numbered-math.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=tmp_path / "pages",
        assets_source_dir=tmp_path / "assets",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")

    assert "\\tag*{(5)}" in chapter
    assert "math-block" in chapter


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


def test_epub_builder_preserves_chart_figure_crop_and_removes_axis_tables(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
Before the figure.

<table><tr><th>Input/Hidden/Output</th><th>Depth</th></tr><tr><td>-1</td><td>2</td></tr></table>

<table><tr><th>Input/Hidden/Output</th><th>Depth</th></tr><tr><td>0</td><td>3</td></tr></table>

<div style="text-align: center;">Figure 1: A residual network and an ODE network.</div>

After the figure.
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 100,
                    "height": 100,
                    "parsing_res_list": [
                        {
                            "block_label": "text",
                            "block_bbox": [0, 10, 8, 46],
                            "block_content": "Neighbor text",
                        },
                        {
                            "block_label": "chart",
                            "block_bbox": [10, 10, 42, 46],
                            "block_content": "Input/Hidden/Output | Depth",
                        },
                        {
                            "block_label": "chart",
                            "block_bbox": [52, 12, 90, 46],
                            "block_content": "Input/Hidden/Output | Depth",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [10, 54, 90, 70],
                            "block_content": "Figure 1: A residual network and an ODE network.",
                        },
                    ],
                },
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    page_image = Image.new("RGB", (100, 100), "white")
    for x in range(0, 8):
        for y in range(10, 46):
            page_image.putpixel((x, y), (200, 0, 0))
    for x in range(10, 90):
        for y in range(10, 46):
            page_image.putpixel((x, y), (20, 80, 160))
    page_image.save(pages_dir / "page-01.png")
    assets_dir = tmp_path / "assets"

    result = build_epub(
        output_path=tmp_path / "figures.epub",
        title="Figures",
        author="",
        original_filename="figures.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=pages_dir,
        assets_source_dir=assets_dir,
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        names = epub.namelist()
        crop_name = "EPUB/assets/figure-crops/page-0001-figure-01.png"
        crop = epub.read(crop_name)

    assert "preserved-figure" in chapter
    assert "Figure 1: A residual network" in chapter
    assert "Input/Hidden/Output" not in chapter
    assert crop_name in names
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(crop)
    with Image.open(crop_path) as image:
        assert image.width >= 80
        assert image.height >= 50
        assert image.getpixel((0, 20)) == (20, 80, 160)


def test_epub_builder_preserves_multiple_plot_crops_without_erasing_earlier_figures(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
<table><tr><th>Iterations</th><th>Loss</th></tr><tr><td>0</td><td>1.0</td></tr></table>

<div style="text-align: center;">(a)</div>

<div style="text-align: center;">(b)</div>

<div style="text-align: center;">Figure 2: Training loss curves.</div>

<table><tr><th>Epoch</th><th>Accuracy</th></tr><tr><td>1</td><td>0.7</td></tr></table>

<div style="text-align: center;">Figure 3: Accuracy curves.</div>
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 1000,
                    "height": 1000,
                    "parsing_res_list": [
                        {
                            "block_label": "table",
                            "block_bbox": [120, 100, 880, 330],
                            "block_content": "Iterations | Loss\n0 | 1.0\n1 | 0.7\n2 | 0.4\n3 | 0.2\n4 | 0.1\n5 | 0.05",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [240, 342, 280, 365],
                            "block_content": "(a)",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [720, 342, 760, 365],
                            "block_content": "(b)",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [120, 380, 880, 430],
                            "block_content": "Figure 2: Training loss curves.",
                        },
                        {
                            "block_label": "chart",
                            "block_bbox": [120, 520, 880, 760],
                            "block_content": "Epoch | Accuracy\n1 | 0.7\n2 | 0.8\n3 | 0.9\n4 | 0.92\n5 | 0.94",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [120, 790, 880, 840],
                            "block_content": "Figure 3: Accuracy curves.",
                        },
                    ],
                },
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    page_image = Image.new("RGB", (1000, 1000), "white")
    for x in range(120, 880):
        for y in range(100, 365):
            page_image.putpixel((x, y), (20, 80, 160))
    for x in range(120, 880):
        for y in range(520, 760):
            page_image.putpixel((x, y), (20, 160, 80))
    page_image.save(pages_dir / "page-01.png")

    result = build_epub(
        output_path=tmp_path / "multi-figures.epub",
        title="Multiple figures",
        author="",
        original_filename="multi-figures.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=pages_dir,
        assets_source_dir=tmp_path / "assets",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        names = epub.namelist()

    assert chapter.count("preserved-figure") == 2
    assert "Figure 2: Training loss curves" in chapter
    assert "Figure 3: Accuracy curves" in chapter
    assert "<table" not in chapter
    assert "Iterations" not in chapter
    assert "EPUB/assets/figure-crops/page-0001-figure-01.png" in names
    assert "EPUB/assets/figure-crops/page-0001-figure-02.png" in names


def test_epub_builder_trims_page_header_from_preserved_figure_crop(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
<table><tr><th>Epoch</th><th>Loss</th></tr><tr><td>0</td><td>1.0</td></tr></table>

<div style="text-align: center;">Figure 4: Loss curves.</div>
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 1000,
                    "height": 1000,
                    "parsing_res_list": [
                        {
                            "block_label": "chart",
                            "block_bbox": [120, 92, 880, 360],
                            "block_content": "Epoch | Loss\n0 | 1.0\n1 | 0.8\n2 | 0.6\n3 | 0.4\n4 | 0.2",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [120, 390, 880, 440],
                            "block_content": "Figure 4: Loss curves.",
                        },
                    ],
                },
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    page_image = Image.new("RGB", (1000, 1000), "white")
    for x in range(70, 930):
        page_image.putpixel((x, 80), (0, 0, 0))
        page_image.putpixel((x, 81), (0, 0, 0))
    for x in range(120, 880):
        for y in range(132, 360):
            page_image.putpixel((x, y), (20, 80, 160))
    page_image.save(pages_dir / "page-01.png")

    result = build_epub(
        output_path=tmp_path / "trimmed-figure.epub",
        title="Trimmed figure",
        author="",
        original_filename="trimmed-figure.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=pages_dir,
        assets_source_dir=tmp_path / "assets",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        crop = epub.read("EPUB/assets/figure-crops/page-0001-figure-01.png")

    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(crop)
    with Image.open(crop_path) as image:
        top_row = [image.getpixel((x, 0)) for x in range(image.width)]
        assert top_row.count((0, 0, 0)) < image.width * 0.1
        assert any(image.getpixel((image.width // 2, y)) == (20, 80, 160) for y in range(0, 16))
        assert image.height < 300


def test_page_header_trim_does_not_remove_upper_panels_from_multirow_plot() -> None:
    image = Image.new("RGB", (760, 300), "white")
    for x in range(20, 740):
        image.putpixel((x, 72), (0, 0, 0))
        image.putpixel((x, 73), (0, 0, 0))
    for x in range(20, 740):
        for y in range(24, 68):
            image.putpixel((x, y), (20, 80, 160))
    for x in range(20, 740):
        for y in range(132, 190):
            image.putpixel((x, y), (20, 160, 80))

    trimmed = _remove_page_header_from_crop(image)

    assert trimmed.size == image.size


def test_epub_builder_trims_outer_whitespace_from_preserved_figure_crop() -> None:
    image = Image.new("RGB", (240, 160), "white")
    for x in range(70, 190):
        for y in range(36, 112):
            image.putpixel((x, y), (20, 80, 160))

    trimmed = _trim_outer_whitespace(image)

    assert trimmed.width < image.width
    assert trimmed.height < image.height
    assert trimmed.width >= 120
    assert trimmed.height >= 76
    assert trimmed.getpixel((trimmed.width // 2, trimmed.height // 2)) == (20, 80, 160)


def test_epub_builder_crops_full_multirow_plot_cluster(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
<table><tr><th>Mask quality rating</th><th>A</th></tr><tr><td>1</td><td>4</td></tr></table>
<div style="text-align: center;">(a) Dataset A</div>
<table><tr><th>Mask quality rating</th><th>B</th></tr><tr><td>1</td><td>6</td></tr></table>
<div style="text-align: center;">(b) Dataset B</div>
<table><tr><th>Mask quality rating</th><th>C</th></tr><tr><td>1</td><td>8</td></tr></table>
<div style="text-align: center;">(c) Dataset C</div>
<div style="text-align: center;">Figure 18: Mask quality rating distributions.</div>
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 1000,
                    "height": 1000,
                    "parsing_res_list": [
                        {
                            "block_label": "chart",
                            "block_bbox": [100, 80, 450, 190],
                            "block_content": "Mask quality rating | A\n1 | 4\n2 | 8\n3 | 16\n4 | 32",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [210, 195, 340, 215],
                            "block_content": "(a) Dataset A",
                        },
                        {
                            "block_label": "chart",
                            "block_bbox": [100, 260, 450, 370],
                            "block_content": "Mask quality rating | B\n1 | 6\n2 | 12\n3 | 18\n4 | 24",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [210, 375, 340, 395],
                            "block_content": "(b) Dataset B",
                        },
                        {
                            "block_label": "chart",
                            "block_bbox": [100, 440, 450, 550],
                            "block_content": "Mask quality rating | C\n1 | 8\n2 | 16\n3 | 24\n4 | 32",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [210, 555, 340, 575],
                            "block_content": "(c) Dataset C",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [100, 600, 780, 640],
                            "block_content": "Figure 18: Mask quality rating distributions.",
                        },
                    ],
                },
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    page_image = Image.new("RGB", (1000, 1000), "white")
    for x in range(100, 450):
        for y in range(80, 190):
            page_image.putpixel((x, y), (20, 80, 160))
        for y in range(260, 370):
            page_image.putpixel((x, y), (20, 160, 80))
        for y in range(440, 550):
            page_image.putpixel((x, y), (160, 80, 20))
    page_image.save(pages_dir / "page-01.png")

    result = build_epub(
        output_path=tmp_path / "multirow-figure.epub",
        title="Multirow figure",
        author="",
        original_filename="multirow-figure.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=pages_dir,
        assets_source_dir=tmp_path / "assets",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        crop = epub.read("EPUB/assets/figure-crops/page-0001-figure-01.png")
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")

    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(crop)
    with Image.open(crop_path) as image:
        colors = {color for _count, color in image.getcolors(maxcolors=1_000_000)}
        assert (20, 80, 160) in colors
        assert (20, 160, 80) in colors
        assert (160, 80, 20) in colors
        assert image.height > 460
    assert "<table" not in chapter


def test_epub_builder_does_not_strip_tables_without_plausible_figure_crop(tmp_path: Path) -> None:
    raw_result = {
        "jobId": "fixture",
        "pages": [
            {
                "markdownText": """
Before the table.

<table><tr><th>Only table data</th></tr><tr><td>42</td></tr></table>

<div style="text-align: center;">Figure 2: A very small detected artifact.</div>
""",
                "markdownImages": {},
                "outputImages": {},
                "prunedResult": {
                    "width": 1000,
                    "height": 1000,
                    "parsing_res_list": [
                        {
                            "block_label": "table",
                            "block_bbox": [500, 500, 540, 530],
                            "block_content": "Only table data",
                        },
                        {
                            "block_label": "figure_title",
                            "block_bbox": [480, 550, 760, 580],
                            "block_content": "Figure 2: A very small detected artifact.",
                        },
                    ],
                },
            }
        ],
    }
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    Image.new("RGB", (1000, 1000), "white").save(pages_dir / "page-01.png")

    result = build_epub(
        output_path=tmp_path / "table-only.epub",
        title="Table only",
        author="",
        original_filename="table-only.pdf",
        raw_result=raw_result,
        bundle=merge_bundles(),
        snapshot_paths=[],
        snapshot_source_dir=pages_dir,
        assets_source_dir=tmp_path / "assets",
    )

    with zipfile.ZipFile(result.output_path) as epub:
        chapter = epub.read("EPUB/text/page-0001.xhtml").decode("utf-8")
        names = epub.namelist()

    assert "preserved-figure" not in chapter
    assert "Only table data" in chapter
    assert not any(name.startswith("EPUB/assets/figure-crops/") for name in names)
