import { describe, expect, it } from "vitest";
import { normalizeMarkdownPages } from "./normalize";

describe("Markdown normalization", () => {
  it("removes repeated headers, footers, and standalone page numbers", () => {
    const pages = normalizeMarkdownPages([
      "Journal Name\n\nA useful para-\ngraph\n\n1",
      "Journal Name\n\ncontinues here.\n\n2",
      "Journal Name\n\nFinal text.\n\n3"
    ]);

    expect(pages[0]?.markdown).toContain("A useful paragraph");
    expect(pages[0]?.markdown).not.toContain("Journal Name");
    expect(pages[1]?.markdown).not.toContain("2");
  });
});

