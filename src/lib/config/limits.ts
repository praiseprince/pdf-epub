import { readOptionalLimitNumberEnv, readOptionalNumberEnv } from "@/lib/server/env";

const VERCEL_BLOB_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024 * 1024;

function optionalMbLimit(name: string, fallback: number) {
  const value = readOptionalLimitNumberEnv(name, fallback);
  return Number.isFinite(value) ? value * 1024 * 1024 : Number.POSITIVE_INFINITY;
}

export function maxPdfSizeBytes() {
  return optionalMbLimit("MAX_PDF_SIZE_MB", Number.POSITIVE_INFINITY);
}

export function maxPdfUploadBytes() {
  const limit = maxPdfSizeBytes();
  return Number.isFinite(limit) ? limit : VERCEL_BLOB_MAX_UPLOAD_BYTES;
}

export function maxPdfPages() {
  return readOptionalLimitNumberEnv("MAX_PDF_PAGES", Number.POSITIVE_INFINITY);
}

export function jobExpirationMinutes() {
  return readOptionalNumberEnv("JOB_EXPIRATION_MINUTES", 60);
}

export function maxImageSizeBytes() {
  return optionalMbLimit("MAX_IMAGE_SIZE_MB", Number.POSITIVE_INFINITY);
}

export function maxTotalAssetBytes() {
  return optionalMbLimit("MAX_TOTAL_ASSET_MB", Number.POSITIVE_INFINITY);
}

export function finalizeImagePageBatchSize() {
  return readOptionalNumberEnv("FINALIZE_IMAGE_PAGE_BATCH", 5);
}

export function finalizeChapterBatchSize() {
  return readOptionalNumberEnv("FINALIZE_CHAPTER_BATCH", 5);
}
