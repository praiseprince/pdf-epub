import { readOptionalNumberEnv } from "@/lib/server/env";

export function maxPdfSizeBytes() {
  return readOptionalNumberEnv("MAX_PDF_SIZE_MB", 50) * 1024 * 1024;
}

export function maxPdfPages() {
  return readOptionalNumberEnv("MAX_PDF_PAGES", 100);
}

export function jobExpirationMinutes() {
  return readOptionalNumberEnv("JOB_EXPIRATION_MINUTES", 60);
}

export function maxImageSizeBytes() {
  return readOptionalNumberEnv("MAX_IMAGE_SIZE_MB", 20) * 1024 * 1024;
}

export function maxTotalAssetBytes() {
  return readOptionalNumberEnv("MAX_TOTAL_ASSET_MB", 300) * 1024 * 1024;
}

