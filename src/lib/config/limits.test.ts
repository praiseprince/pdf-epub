import { afterEach, describe, expect, it } from "vitest";
import {
  maxImageSizeBytes,
  maxPdfPages,
  maxPdfSizeBytes,
  maxPdfUploadBytes,
  maxTotalAssetBytes,
  pdfInspectionMaxBytes
} from "./limits";

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("configurable limits", () => {
  it("uses platform-aligned defaults", () => {
    delete process.env.MAX_PDF_SIZE_MB;
    delete process.env.MAX_PDF_PAGES;
    delete process.env.MAX_IMAGE_SIZE_MB;
    delete process.env.MAX_TOTAL_ASSET_MB;
    delete process.env.PDF_INSPECTION_MAX_MB;

    expect(maxPdfSizeBytes()).toBe(1024 * 1024 * 1024);
    expect(maxPdfPages()).toBe(1000);
    expect(maxPdfUploadBytes()).toBe(1024 * 1024 * 1024);
    expect(maxImageSizeBytes()).toBe(256 * 1024 * 1024);
    expect(maxTotalAssetBytes()).toBe(1024 * 1024 * 1024);
    expect(pdfInspectionMaxBytes()).toBe(256 * 1024 * 1024);
  });

  it("treats 0 as no app-level cap", () => {
    process.env.MAX_PDF_SIZE_MB = "0";
    process.env.MAX_PDF_PAGES = "0";

    expect(maxPdfSizeBytes()).toBe(Number.POSITIVE_INFINITY);
    expect(maxPdfPages()).toBe(Number.POSITIVE_INFINITY);
    expect(Number.isFinite(maxPdfUploadBytes())).toBe(true);
  });

  it("uses finite configured limits when provided", () => {
    process.env.MAX_PDF_SIZE_MB = "10";
    process.env.MAX_PDF_PAGES = "25";

    expect(maxPdfSizeBytes()).toBe(10 * 1024 * 1024);
    expect(maxPdfPages()).toBe(25);
    expect(maxPdfUploadBytes()).toBe(10 * 1024 * 1024);
  });
});
