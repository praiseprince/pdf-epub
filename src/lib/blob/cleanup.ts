import { del, list, type ListBlobResultBlob } from "@vercel/blob";
import { jobExpirationMinutes } from "@/lib/config/limits";
import { isValidJobBlobPath } from "./paths";

export function expiredTmpPathnames(blobs: ListBlobResultBlob[], now = Date.now()) {
  const cutoff = now - jobExpirationMinutes() * 60 * 1000;
  return blobs
    .filter((blob) => blob.pathname.startsWith("tmp/"))
    .filter((blob) => isValidJobBlobPath(blob.pathname))
    .filter((blob) => blob.uploadedAt.getTime() < cutoff)
    .map((blob) => blob.pathname);
}

export async function deleteJobBlobs(jobId: string, includeResult: boolean) {
  const prefix = `tmp/${jobId}/`;
  const found = await list({ prefix, limit: 1000 });
  const pathnames = found.blobs
    .map((blob) => blob.pathname)
    .filter(isValidJobBlobPath)
    .filter((pathname) => includeResult || !pathname.endsWith("/result.epub"));

  if (pathnames.length > 0) {
    await del(pathnames);
  }

  return pathnames.length;
}

export async function cleanupExpiredTmpObjects() {
  let cursor: string | undefined;
  let deleted = 0;

  do {
    const page = await list({
      prefix: "tmp/",
      limit: 1000,
      ...(cursor ? { cursor } : {})
    });
    const expired = expiredTmpPathnames(page.blobs);
    if (expired.length > 0) {
      await del(expired);
      deleted += expired.length;
    }
    cursor = page.cursor;
    if (!page.hasMore) {
      break;
    }
  } while (cursor);

  return deleted;
}
