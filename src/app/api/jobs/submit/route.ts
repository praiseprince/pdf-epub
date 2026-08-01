import { unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { NextResponse } from "next/server";
import { z } from "zod";
import { assertPathBelongsToJob } from "@/lib/blob/paths";
import { readPrivateBlobBuffer } from "@/lib/blob/io";
import { createSignedGetUrl } from "@/lib/blob/signed-url";
import { maxPdfSizeBytes } from "@/lib/config/limits";
import { sanitizeMetadataText } from "@/lib/files/sanitize";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyUploadToken, signJobToken } from "@/lib/jobs/tokens";
import { submitPaddleDocumentFile, submitPaddleDocumentUrl, mapPaddleError } from "@/lib/paddle/client";
import { inspectPdfBytes } from "@/lib/pdf/inspect";

export const runtime = "nodejs";
export const maxDuration = 240;

const submitSchema = z.object({
  uploadToken: z.string().min(1),
  inputPath: z.string().min(1),
  title: z.string().optional(),
  author: z.string().optional()
});

export async function POST(request: Request) {
  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const parsed = submitSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return jsonError("Upload failed.");
  }

  const uploadClaims = await verifyUploadToken(parsed.data.uploadToken).catch(() => null);
  if (!uploadClaims || uploadClaims.inputPath !== parsed.data.inputPath) {
    return jsonError("The conversion expired.", 401);
  }

  if (!assertPathBelongsToJob(parsed.data.inputPath, uploadClaims.jobId)) {
    return jsonError("The temporary file has already been deleted.", 400);
  }

  let pdfBytes: Uint8Array;
  try {
    pdfBytes = await readPrivateBlobBuffer(parsed.data.inputPath, maxPdfSizeBytes());
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload failed.";
    return jsonError(message);
  }
  const inspection = await inspectPdfBytes(pdfBytes);
  if (!inspection.ok) {
    return jsonError(inspection.message);
  }

  let paddleJob;
  try {
    const signedPdfUrl = await createSignedGetUrl(parsed.data.inputPath);
    try {
      paddleJob = await submitPaddleDocumentUrl(signedPdfUrl);
    } catch {
      const tmpPdfPath = join(tmpdir(), `${uploadClaims.jobId}.pdf`);
      await writeFile(tmpPdfPath, pdfBytes);
      try {
        paddleJob = await submitPaddleDocumentFile(tmpPdfPath);
      } finally {
        await unlink(tmpPdfPath).catch(() => undefined);
      }
    }
  } catch (error) {
    const publicError = mapPaddleError(error);
    return NextResponse.json({ error: publicError.message }, { status: publicError.status });
  }

  const title = sanitizeMetadataText(parsed.data.title, uploadClaims.originalFilename.replace(/\.pdf$/i, ""));
  const author = sanitizeMetadataText(parsed.data.author);
  const jobToken = await signJobToken({
    jobId: uploadClaims.jobId,
    inputPath: uploadClaims.inputPath,
    originalFilename: uploadClaims.originalFilename,
    paddleJobId: paddleJob.jobId,
    title,
    ...(author ? { author } : {})
  });

  return NextResponse.json({
    jobToken,
    pageCount: inspection.pageCount,
    stage: "Reading document"
  });
}
