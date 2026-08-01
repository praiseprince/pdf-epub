import { PDFDocument } from "pdf-lib";
import { maxPdfPages } from "@/lib/config/limits";
import { bufferHasPdfSignature } from "@/lib/files/pdf";

export type PdfInspection =
  | {
      ok: true;
      pageCount: number;
    }
  | {
      ok: false;
      message: string;
    };

export async function inspectPdfBytes(bytes: Uint8Array, pageLimit = maxPdfPages()): Promise<PdfInspection> {
  if (!bufferHasPdfSignature(bytes)) {
    return { ok: false, message: "This file is not a valid PDF." };
  }

  try {
    const pdf = await PDFDocument.load(bytes, {
      ignoreEncryption: false,
      updateMetadata: false
    });
    const pageCount = pdf.getPageCount();

    if (Number.isFinite(pageLimit) && pageCount > pageLimit) {
      return { ok: false, message: "This PDF exceeds the page limit." };
    }

    return { ok: true, pageCount };
  } catch (error) {
    const message = error instanceof Error ? error.message.toLowerCase() : "";
    if (message.includes("encrypted") || message.includes("password")) {
      return { ok: false, message: "This PDF is password protected." };
    }

    return { ok: false, message: "This file is not a valid PDF." };
  }
}
