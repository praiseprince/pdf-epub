import { NextRequest, NextResponse } from "next/server";
import { resultEpubPath } from "@/lib/blob/paths";
import { createSignedGetUrl } from "@/lib/blob/signed-url";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyJobToken } from "@/lib/jobs/tokens";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const token = request.nextUrl.searchParams.get("jobToken");
  if (!token) {
    return jsonError("The conversion expired.", 401);
  }

  const jobClaims = await verifyJobToken(token).catch(() => null);
  if (!jobClaims) {
    return jsonError("The conversion expired.", 401);
  }

  const downloadUrl = await createSignedGetUrl(resultEpubPath(jobClaims.jobId), 60 * 60 * 1000);
  return NextResponse.json({ downloadUrl });
}

