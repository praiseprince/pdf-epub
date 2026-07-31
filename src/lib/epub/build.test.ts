import { unzipSync, strFromU8 } from "fflate";
import { describe, expect, it } from "vitest";
import { buildEpubFromPaddleResult, firstZipEntryIsStoredMimetype } from "./build";

describe("EPUB builder", () => {
  it("creates an EPUB 3 archive with stored mimetype first, nav, manifest, and formulas", async () => {
    const epub = await buildEpubFromPaddleResult(
      {
        jobId: "job-1",
        pages: [
          {
            markdownText: [
              "# A Tiny Paper",
              "",
              "This paragraph has inline math $x^2$ and a citation [1].",
              "",
              "$$\\frac{a}{b}$$",
              "",
              "| A | B |",
              "| - | - |",
              "| 1 | 2 |",
              "",
              "[^1]: A footnote."
            ].join("\n"),
            markdownImages: {},
            outputImages: {}
          }
        ]
      },
      {
        title: "A Tiny Paper",
        author: "Ada Lovelace",
        originalFilename: "tiny.pdf"
      }
    );

    expect(firstZipEntryIsStoredMimetype(epub.buffer)).toBe(true);
    const entries = unzipSync(epub.buffer);
    expect(entries["META-INF/container.xml"]).toBeDefined();
    expect(entries["EPUB/package.opf"]).toBeDefined();
    expect(entries["EPUB/nav.xhtml"]).toBeDefined();
    expect(entries["EPUB/text/chapter-1.xhtml"]).toBeDefined();

    const packageXml = strFromU8(entries["EPUB/package.opf"]!);
    expect(packageXml).toContain('properties="nav"');
    expect(packageXml).toContain('media-type="image/svg+xml"');

    const chapter = strFromU8(entries["EPUB/text/chapter-1.xhtml"]!);
    expect(chapter).toContain("math-inline");
    expect(chapter).toContain("math-block");
    expect(chapter).toContain("<table>");
    expect(chapter).toContain('epub:type="footnotes"');
  });
});

