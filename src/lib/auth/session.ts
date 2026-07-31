import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { readRequiredEnv } from "@/lib/server/env";
import {
  SESSION_MAX_AGE_SECONDS,
  signSessionToken,
  verifySessionToken
} from "@/lib/auth/tokens";

export const SESSION_COOKIE_NAME = "pdf_epub_session";

export async function hasValidSession(): Promise<boolean> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;

  if (!token) {
    return false;
  }

  try {
    await verifySessionToken(token, readRequiredEnv("SESSION_SECRET"));
    return true;
  } catch {
    return false;
  }
}

export async function attachSessionCookie(response: NextResponse) {
  const token = await signSessionToken(readRequiredEnv("SESSION_SECRET"));
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS
  });
}

export function clearSessionCookie(response: NextResponse) {
  response.cookies.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0
  });
}

