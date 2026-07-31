import { NextResponse } from "next/server";
import { cleanupExpiredTmpObjects } from "@/lib/blob/cleanup";
import { readRequiredEnv } from "@/lib/server/env";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function GET(request: Request) {
  const secret = request.headers.get("x-cron-secret");
  if (!secret || secret !== readRequiredEnv("CRON_SECRET")) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const deleted = await cleanupExpiredTmpObjects();
  return NextResponse.json({ ok: true, deleted });
}

