import { NextResponse } from "next/server";
import { z } from "zod";
import { verifyPin } from "@/lib/auth/password";
import { attachSessionCookie } from "@/lib/auth/session";

export const runtime = "nodejs";

const loginSchema = z.object({
  pin: z.string().min(1).max(256)
});

export async function POST(request: Request) {
  const parsed = loginSchema.safeParse(await request.json().catch(() => null));

  if (!parsed.success) {
    return NextResponse.json({ error: "Enter the PIN." }, { status: 400 });
  }

  let accepted = false;
  try {
    accepted = await verifyPin(parsed.data.pin);
  } catch {
    return NextResponse.json({ error: "PIN login is not configured." }, { status: 500 });
  }

  if (!accepted) {
    return NextResponse.json({ error: "The PIN was not accepted." }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  await attachSessionCookie(response);
  return response;
}

