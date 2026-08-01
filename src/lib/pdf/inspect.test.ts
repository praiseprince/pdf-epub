import { PDFDocument } from "pdf-lib";
import { describe, expect, it } from "vitest";
import { inspectPdfBytes } from "./inspect";

async function samplePdf(pageCount: number) {
  const pdf = await PDFDocument.create();
  for (let i = 0; i < pageCount; i += 1) {
    pdf.addPage();
  }
  return pdf.save();
}

describe("PDF inspection", () => {
  it("counts pages in valid PDFs", async () => {
    await expect(inspectPdfBytes(await samplePdf(2), 10)).resolves.toEqual({
      ok: true,
      pageCount: 2
    });
  });

  it("rejects invalid signatures", async () => {
    await expect(inspectPdfBytes(new TextEncoder().encode("not a pdf"), 10)).resolves.toEqual({
      ok: false,
      message: "This file is not a valid PDF."
    });
  });

  it("rejects PDFs over the page limit", async () => {
    await expect(inspectPdfBytes(await samplePdf(3), 2)).resolves.toEqual({
      ok: false,
      message: "This PDF exceeds the page limit."
    });
  });

  it("allows disabled page limits", async () => {
    await expect(inspectPdfBytes(await samplePdf(3), Number.POSITIVE_INFINITY)).resolves.toEqual({
      ok: true,
      pageCount: 3
    });
  });
});
