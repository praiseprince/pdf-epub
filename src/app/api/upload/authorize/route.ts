import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { sourcePdfPath } from "@/lib/blob/paths";
import { maxPdfSizeBytes, maxPdfUploadBytes } from "@/lib/config/limits";
import { hasPdfExtension, hasPdfMimeType } from "@/lib/files/pdf";
import { sanitizeFilename } from "@/lib/files/sanitize";
import { jsonError, requireSession } from "@/lib/http/api";
import { signUploadToken, verifyUploadToken } from "@/lib/jobs/tokens";

export const runtime = "nodejs";

const initialAuthorizeSchema = z.object({
  filename: z.string().min(1).max(240),
  size: z.number().int().positive(),
  contentType: z.string().optional()
});

const uploadClientPayloadSchema = z.object({
  uploadToken: z.string().min(1)
});

function isHandleUploadBody(body: unknown): body is HandleUploadBody {
  return (
    typeof body === "object" &&
    body !== null &&
    "type" in body &&
    typeof (body as { type?: unknown }).type === "string" &&
    (body as { type: string }).type.startsWith("blob.")
  );
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);

  if (isHandleUploadBody(body)) {
    const unauthorized = await requireSession();
    if (unauthorized) {
      return unauthorized;
    }

    try {
      const jsonResponse = await handleUpload({
        body,
        request,
        onBeforeGenerateToken: async (pathname, clientPayload) => {
          const parsedPayload = uploadClientPayloadSchema.parse(
            JSON.parse(clientPayload ?? "{}") as unknown
          );
          const uploadClaims = await verifyUploadToken(parsedPayload.uploadToken);

          if (pathname !== uploadClaims.inputPath) {
            throw new Error("Upload path was not authorized.");
          }

          return {
            allowedContentTypes: ["application/pdf", "application/x-pdf"],
            maximumSizeInBytes: maxPdfUploadBytes(),
            validUntil: Date.now() + 15 * 60 * 1000,
            addRandomSuffix: false,
            allowOverwrite: false,
            cacheControlMaxAge: 0,
            tokenPayload: JSON.stringify({
              jobId: uploadClaims.jobId,
              inputPath: uploadClaims.inputPath
            })
          };
        }
      });

      return NextResponse.json(jsonResponse);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Upload authorization failed.";
      return jsonError(message);
    }
  }

  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const parsed = initialAuthorizeSchema.safeParse(body);
  if (!parsed.success) {
    return jsonError("Choose a PDF before uploading.");
  }

  const filename = sanitizeFilename(parsed.data.filename);
  if (!hasPdfExtension(filename) || !hasPdfMimeType(parsed.data.contentType)) {
    return jsonError("This file is not a valid PDF.");
  }

  const sizeLimit = maxPdfSizeBytes();
  if (Number.isFinite(sizeLimit) && parsed.data.size > sizeLimit) {
    return jsonError("This PDF exceeds the configured size limit.");
  }

  const jobId = randomUUID();
  const inputPath = sourcePdfPath(jobId);
  const uploadToken = await signUploadToken({
    jobId,
    inputPath,
    originalFilename: filename,
    size: parsed.data.size
  });

  return NextResponse.json({
    jobId,
    inputPath,
    uploadToken,
    maxSizeBytes: maxPdfUploadBytes()
  });
}
