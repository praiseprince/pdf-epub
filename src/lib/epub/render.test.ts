import { describe, expect, it } from "vitest";
import { parseMarkdown } from "./normalize";
import { renderRoot } from "./render";
import { ResourceRegistry } from "./resources";

describe("XHTML renderer figures", () => {
  it("associates adjacent figure captions with image-only paragraphs", async () => {
    const root = parseMarkdown("![Diagram](images/diagram.png)\n\nFigure 1. A useful diagram.");
    const html = await renderRoot(root, {
      resources: new ResourceRegistry(),
      imageMap: new Map([["images/diagram.png", "../assets/images/diagram.png"]]),
      warnings: [],
      chapterId: "chapter-1"
    });

    expect(html).toContain("<figure>");
    expect(html).toContain('<img src="../assets/images/diagram.png" alt="Diagram" />');
    expect(html).toContain("<figcaption>Figure 1. A useful diagram.</figcaption>");
  });

  it("does not embed external image URLs when an image resource is missing", async () => {
    const warnings: string[] = [];
    const root = parseMarkdown("![Remote](https://example.com/image.jpg)");
    const html = await renderRoot(root, {
      resources: new ResourceRegistry(),
      imageMap: new Map(),
      warnings,
      chapterId: "chapter-1"
    });

    expect(html).not.toContain("https://example.com/image.jpg");
    expect(html).toContain("image-fallback");
    expect(warnings).toHaveLength(1);
  });
});

describe("XHTML renderer tables", () => {
  it("renders GFM tables as semantic tables with adjacent captions", async () => {
    const root = parseMarkdown("| A | B |\n| - | - |\n| 1 | 2 |\n\nTable 1. Small values.");
    const html = await renderRoot(root, {
      resources: new ResourceRegistry(),
      imageMap: new Map(),
      warnings: [],
      chapterId: "chapter-1"
    });

    expect(html).toContain("<table>");
    expect(html).toContain("<caption>Table 1. Small values.</caption>");
    expect(html).toContain("<thead>");
    expect(html).toContain("<th>A</th>");
    expect(html).toContain("<td>1</td>");
  });
});
