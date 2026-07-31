import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { buildEpubFromPaddleResult } from "../src/lib/epub/build";

const outputPath = process.argv[2] ?? "tmp/sample.epub";

const epub = await buildEpubFromPaddleResult(
  {
    jobId: "sample",
    pages: [
      {
        markdownText: [
          "# Sample Document",
          "",
          "This sample validates the generated EPUB package, navigation, table, footnote, and $x^2$ formula resources.",
          "",
          "| Item | Value |",
          "| - | - |",
          "| Alpha | 1 |",
          "",
          "Table 1. Sample table.",
          "",
          "[^1]: Sample note."
        ].join("\n"),
        markdownImages: {},
        outputImages: {}
      }
    ]
  },
  {
    title: "Sample Document",
    author: "Private PDF to EPUB",
    originalFilename: "sample.pdf"
  }
);

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, epub.buffer);
console.log(outputPath);

