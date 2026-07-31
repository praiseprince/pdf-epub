import { put } from "@vercel/blob";
import { NextResponse } from "next/server";
import { z } from "zod";
import { resultEpubPath } from "@/lib/blob/paths";
import { createSignedGetUrl } from "@/lib/blob/signed-url";
import { buildEpubFromPaddleResult } from "@/lib/epub/build";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyJobToken } from "@/lib/jobs/tokens";
import { getPaddleDocumentResult, mapPaddleError } from "@/lib/paddle/client";

export const runtime = "nodejs";
export const maxDuration = 300;

const finalizeSchema = z.object({
  jobToken: z.string().min(1)
});

export async function POST(request: Request) {
  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const parsed = finalizeSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return jsonError("The conversion expired.", 401);
  }

  const jobClaims = await verifyJobToken(parsed.data.jobToken).catch(() => null);
  if (!jobClaims) {
    return jsonError("The conversion expired.", 401);
  }

  let paddleResult;
  try {
    paddleResult = await getPaddleDocumentResult(jobClaims.paddleJobId);
  } catch (error) {
    const publicError = mapPaddleError(error);
    return NextResponse.json({ error: publicError.message }, { status: publicError.status });
  }

  let epub;
  try {
    epub = await buildEpubFromPaddleResult(paddleResult, {
      title: jobClaims.title ?? jobClaims.originalFilename.replace(/\.pdf$/i, ""),
      ...(jobClaims.author ? { author: jobClaims.author } : {}),
      originalFilename: jobClaims.originalFilename
    });
  } catch {
    return jsonError("EPUB generation failed.", 500);
  }

  const outputPath = resultEpubPath(jobClaims.jobId);
  try {
    await put(outputPath, epub.buffer, {
      access: "private",
      contentType: "application/epub+zip",
      allowOverwrite: true,
      cacheControlMaxAge: 60 * 60
    });
    const downloadUrl = await createSignedGetUrl(outputPath, 60 * 60 * 1000);

    return NextResponse.json({
      downloadUrl,
      warnings: epub.warnings,
      outputPath
    });
  } catch {
    return jsonError("EPUB generation failed.", 500);
  }
}

