import { createWriteStream } from "node:fs";
import { unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { NextResponse } from "next/server";
import { z } from "zod";
import { assertPathBelongsToJob } from "@/lib/blob/paths";
import { getPrivateBlobStream, readPrivateBlobBuffer, readPrivateBlobPrefix } from "@/lib/blob/io";
import { createSignedGetUrl } from "@/lib/blob/signed-url";
import { maxPdfPages, maxPdfSizeBytes } from "@/lib/config/limits";
import { bufferHasPdfSignature } from "@/lib/files/pdf";
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

async function inspectUploadedPdf(inputPath: string) {
  const pageLimit = maxPdfPages();
  if (!Number.isFinite(pageLimit)) {
    const prefix = await readPrivateBlobPrefix(inputPath, 8);
    if (!bufferHasPdfSignature(prefix)) {
      return {
        ok: false as const,
        message: "This file is not a valid PDF."
      };
    }

    return {
      ok: true as const,
      pageCount: null,
      pdfBytes: undefined
    };
  }

  const pdfBytes = await readPrivateBlobBuffer(inputPath, maxPdfSizeBytes());
  const inspection = await inspectPdfBytes(pdfBytes, pageLimit);
  if (!inspection.ok) {
    return inspection;
  }

  return {
    ok: true as const,
    pageCount: inspection.pageCount,
    pdfBytes
  };
}

async function writePrivatePdfToTempFile(inputPath: string, outputPath: string) {
  const result = await getPrivateBlobStream(inputPath);
  const sizeLimit = maxPdfSizeBytes();
  if (Number.isFinite(sizeLimit) && result.blob.size > sizeLimit) {
    throw new Error("This PDF exceeds the configured size limit.");
  }

  await pipeline(
    Readable.fromWeb(result.stream as unknown as Parameters<typeof Readable.fromWeb>[0]),
    createWriteStream(outputPath)
  );
}

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

  let pdfBytes: Uint8Array | undefined;
  let pageCount: number | null;
  try {
    const inspection = await inspectUploadedPdf(parsed.data.inputPath);
    if (!inspection.ok) {
      return jsonError(inspection.message);
    }
    pdfBytes = inspection.pdfBytes;
    pageCount = inspection.pageCount;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload failed.";
    return jsonError(message);
  }

  let paddleJob;
  try {
    const signedPdfUrl = await createSignedGetUrl(parsed.data.inputPath);
    try {
      paddleJob = await submitPaddleDocumentUrl(signedPdfUrl);
    } catch {
      const tmpPdfPath = join(tmpdir(), `${uploadClaims.jobId}.pdf`);
      try {
        if (pdfBytes) {
          await writeFile(tmpPdfPath, pdfBytes);
        } else {
          await writePrivatePdfToTempFile(parsed.data.inputPath, tmpPdfPath);
        }
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
    pageCount,
    stage: "Reading document"
  });
}
