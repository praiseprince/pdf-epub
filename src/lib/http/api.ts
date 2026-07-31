import { NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth/session";

export async function requireSession() {
  if (await hasValidSession()) {
    return null;
  }

  return NextResponse.json({ error: "PIN session required." }, { status: 401 });
}

export function jsonError(message: string, status = 400) {
  return NextResponse.json({ error: message }, { status });
}

