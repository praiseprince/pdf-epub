import { NextResponse } from "next/server";
import { z } from "zod";
import { runChunkedFinalizeStep } from "@/lib/epub/chunked-finalize";
import { jsonError, requireSession } from "@/lib/http/api";
import { verifyJobToken } from "@/lib/jobs/tokens";
import { getPaddleDocumentResult, mapPaddleError } from "@/lib/paddle/client";

export const runtime = "nodejs";
export const maxDuration = 120;

const finalizeSchema = z.object({
  jobToken: z.string().min(1)
});

class PaddleResultError extends Error {
  constructor(readonly originalError: unknown) {
    super("PaddleOCR result could not be loaded.");
  }
}

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

  try {
    const result = await runChunkedFinalizeStep(jobClaims, async () => {
      try {
        return await getPaddleDocumentResult(jobClaims.paddleJobId);
      } catch (error) {
        throw new PaddleResultError(error);
      }
    });
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof PaddleResultError) {
      const publicError = mapPaddleError(error.originalError);
      return NextResponse.json({ error: publicError.message }, { status: publicError.status });
    }
    return jsonError("EPUB generation failed.", 500);
  }
}
