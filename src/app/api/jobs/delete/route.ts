import { NextResponse } from "next/server";
import { z } from "zod";
import { deleteJobBlobs } from "@/lib/blob/cleanup";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyJobToken, verifyUploadToken } from "@/lib/jobs/tokens";

export const runtime = "nodejs";
export const maxDuration = 60;

const deleteSchema = z
  .object({
    jobToken: z.string().optional(),
    uploadToken: z.string().optional()
  })
  .refine((body) => body.jobToken || body.uploadToken);

export async function POST(request: Request) {
  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const parsed = deleteSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return jsonError("The temporary file has already been deleted.");
  }

  const claims = parsed.data.jobToken
    ? await verifyJobToken(parsed.data.jobToken).catch(() => null)
    : await verifyUploadToken(parsed.data.uploadToken ?? "").catch(() => null);

  if (!claims) {
    return jsonError("The conversion expired.", 401);
  }

  const deleted = await deleteJobBlobs(claims.jobId, true);
  return NextResponse.json({ ok: true, deleted });
}

