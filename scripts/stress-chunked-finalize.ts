import { mkdir, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { PDFDocument, StandardFonts, rgb } from "pdf-lib";
import { deleteJobBlobs } from "../src/lib/blob/cleanup";
import { resultEpubPath, sourcePdfPath } from "../src/lib/blob/paths";
import { readPrivateBlobBuffer } from "../src/lib/blob/io";
import { runChunkedFinalizeStep } from "../src/lib/epub/chunked-finalize";
import type { JobTokenClaims } from "../src/lib/jobs/tokens";
import { inspectPdfBytes } from "../src/lib/pdf/inspect";

const PAGE_COUNT = Number.parseInt(process.env.STRESS_PAGE_COUNT ?? "150", 10);

async function makeLargePdf(pathname: string) {
  const pdf = await PDFDocument.create();
  const regular = await pdf.embedFont(StandardFonts.Helvetica);
  const bold = await pdf.embedFont(StandardFonts.HelveticaBold);

  for (let index = 0; index < PAGE_COUNT; index += 1) {
    const page = pdf.addPage([612, 792]);
    const { width, height } = page.getSize();
    const pageNumber = index + 1;

    page.drawText(`Synthetic research stress page ${pageNumber}`, {
      x: 54,
      y: height - 64,
      size: 16,
      font: bold,
      color: rgb(0.05, 0.18, 0.16)
    });
    page.drawText(
      "Dense equations, chart-like geometry, table rows, and repeated headers make this useful for conversion stress tests.",
      {
        x: 54,
        y: height - 92,
        size: 9,
        font: regular,
        maxWidth: 500,
        lineHeight: 12
      }
    );

    for (let row = 0; row < 12; row += 1) {
      page.drawLine({
        start: { x: 54, y: height - 140 - row * 22 },
        end: { x: width - 54, y: height - 140 - row * 22 },
        thickness: row % 3 === 0 ? 1.2 : 0.5,
        color: rgb(0.2, 0.2, 0.2)
      });
    }

    for (let bar = 0; bar < 16; bar += 1) {
      page.drawRectangle({
        x: 60 + bar * 28,
        y: 210,
        width: 16,
        height: 30 + ((bar * pageNumber) % 130),
        color: rgb(0.05 + (bar % 4) * 0.04, 0.35, 0.32 + (bar % 3) * 0.05)
      });
    }

    for (let line = 0; line < 18; line += 1) {
      page.drawText(`E_${line}_${pageNumber} = alpha_${line} x^2 + beta_${pageNumber} / sqrt(n + ${line + 1})`, {
        x: 58,
        y: 560 - line * 16,
        size: 8.5,
        font: regular
      });
    }
  }

  const bytes = await pdf.save();
  await writeFile(pathname, bytes);
  return bytes;
}

function makePaddleResult() {
  return {
    jobId: "synthetic-large",
    pages: Array.from({ length: PAGE_COUNT }, (_, index) => {
      const page = index + 1;
      return {
        markdownText: [
          `# Synthetic Section ${page}`,
          "",
          `This is a dense synthetic research page ${page} with equations, tables, and chart captions.`,
          "",
          "$$",
          `L_${page}(\\theta)=\\sum_{i=1}^{${20 + (page % 30)}} \\log p_\\theta(x_i) - \\lambda \\|\\theta\\|_2^2`,
          "$$",
          "",
          "| Metric | Baseline | Proposed |",
          "| --- | ---: | ---: |",
          `| Accuracy | ${(80 + (page % 17) / 10).toFixed(1)} | ${(86 + (page % 11) / 10).toFixed(1)} |`,
          `| Loss | ${(1.2 + (page % 9) / 100).toFixed(3)} | ${(0.8 + (page % 7) / 100).toFixed(3)} |`,
          "",
          `Figure ${page}. A synthetic diagram-intensive page represented in Markdown.`
        ].join("\n"),
        markdownImages: {},
        outputImages: {}
      };
    })
  };
}

async function main() {
  await mkdir("tmp", { recursive: true });
  const pdfPath = `tmp/stress-${PAGE_COUNT}-page.pdf`;
  const epubPath = `tmp/stress-${PAGE_COUNT}-page.epub`;
  const pdfBytes = await makeLargePdf(pdfPath);
  const inspection = await inspectPdfBytes(pdfBytes, Number.POSITIVE_INFINITY);
  if (!inspection.ok) {
    throw new Error(inspection.message);
  }

  const jobId = randomUUID();
  const claims: JobTokenClaims = {
    kind: "job",
    jobId,
    inputPath: sourcePdfPath(jobId),
    originalFilename: `stress-${PAGE_COUNT}-page.pdf`,
    paddleJobId: "synthetic-large",
    title: `${PAGE_COUNT}-page stress conversion`,
    createdAt: Date.now(),
    expiresAt: Date.now() + 60 * 60 * 1000
  };

  let steps = 0;
  let ready = false;
  while (!ready) {
    steps += 1;
    const result = await runChunkedFinalizeStep(claims, async () => makePaddleResult());
    console.log(`${steps}: ${result.stage}`);
    ready = result.state === "ready";
  }

  const epub = await readPrivateBlobBuffer(resultEpubPath(jobId), Number.POSITIVE_INFINITY);
  await writeFile(epubPath, epub);
  await deleteJobBlobs(jobId, true).catch(() => undefined);

  console.log(`PDF: ${pdfPath}`);
  console.log(`EPUB: ${epubPath}`);
  console.log(`Pages: ${inspection.pageCount}`);
  console.log(`Finalize steps: ${steps}`);
  console.log(`EPUB bytes: ${epub.byteLength}`);
}

await main();
