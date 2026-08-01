import { describe, expect, it } from "vitest";
import {
  finalizeStatePath,
  isValidJobBlobPath,
  jobIdFromPath,
  resultEpubPath,
  sourcePdfPath,
  stagedChapterPath,
  stagedResourcePath
} from "@/lib/blob/paths";
import { bufferHasPdfSignature, hasPdfExtension, hasPdfMimeType } from "./pdf";
import { sanitizeFilename, sanitizeMetadataText } from "./sanitize";

const jobId = "123e4567-e89b-12d3-a456-426614174000";

describe("PDF validation helpers", () => {
  it("checks extension, MIME type, and signature", () => {
    expect(hasPdfExtension("paper.PDF")).toBe(true);
    expect(hasPdfMimeType("application/pdf")).toBe(true);
    expect(bufferHasPdfSignature(new TextEncoder().encode("%PDF-1.7"))).toBe(true);
    expect(bufferHasPdfSignature(new TextEncoder().encode("nope"))).toBe(false);
  });
});

describe("filename and metadata sanitizing", () => {
  it("removes paths, traversal, controls, and unsafe characters", () => {
    expect(sanitizeFilename("../weird/<paper>.pdf")).toBe("_paper_.pdf");
    expect(sanitizeMetadataText("A\u0000 <Title>")).toBe("A Title");
  });
});

describe("blob path validation", () => {
  it("accepts only tmp job namespace paths", () => {
    expect(sourcePdfPath(jobId)).toBe(`tmp/${jobId}/source.pdf`);
    expect(resultEpubPath(jobId)).toBe(`tmp/${jobId}/result.epub`);
    expect(isValidJobBlobPath(sourcePdfPath(jobId))).toBe(true);
    expect(isValidJobBlobPath(finalizeStatePath(jobId))).toBe(true);
    expect(isValidJobBlobPath(stagedChapterPath(jobId, "text/chapter-1.xhtml"))).toBe(true);
    expect(isValidJobBlobPath(stagedResourcePath(jobId, "assets/formulas/hash.svg"))).toBe(true);
    expect(isValidJobBlobPath(`tmp/${jobId}/assets/image.png`)).toBe(true);
    expect(jobIdFromPath(sourcePdfPath(jobId))).toBe(jobId);
    expect(isValidJobBlobPath(`tmp/${jobId}/../source.pdf`)).toBe(false);
    expect(isValidJobBlobPath("other/source.pdf")).toBe(false);
  });
});
