import { NextResponse } from "next/server";
import { z } from "zod";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyJobToken } from "@/lib/jobs/tokens";
import { getPaddleStatus, mapPaddleError } from "@/lib/paddle/client";

export const runtime = "nodejs";
export const maxDuration = 30;

const statusSchema = z.object({
  jobToken: z.string().min(1)
});

export async function POST(request: Request) {
  const unauthorized = await requireSession();
  if (unauthorized) {
    return unauthorized;
  }

  const parsed = statusSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return jsonError("The conversion expired.", 401);
  }

  const jobClaims = await verifyJobToken(parsed.data.jobToken).catch(() => null);
  if (!jobClaims) {
    return jsonError("The conversion expired.", 401);
  }

  try {
    const status = await getPaddleStatus(jobClaims.paddleJobId);
    const state = status.state === "done" ? "completed" : status.state;

    return NextResponse.json({
      state,
      stage: state === "completed" ? "Processing formulas and figures" : "Reading document",
      progress: status.progress
        ? {
            totalPages: status.progress.totalPages,
            extractedPages: status.progress.extractedPages
          }
        : null,
      error: status.errorMsg
    });
  } catch (error) {
    const publicError = mapPaddleError(error);
    return NextResponse.json({ error: publicError.message }, { status: publicError.status });
  }
}

