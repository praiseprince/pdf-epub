import { jwtVerify, SignJWT } from "jose";
import { randomUUID } from "node:crypto";
import { z } from "zod";

const encoder = new TextEncoder();

export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export const sessionClaimsSchema = z
  .object({
    kind: z.literal("session"),
    jti: z.string().uuid()
  })
  .passthrough();

function keyFromSecret(secret: string) {
  if (secret.length < 32) {
    throw new Error("SESSION_SECRET must be at least 32 characters.");
  }

  return encoder.encode(secret);
}

export async function signSessionToken(
  secret: string,
  maxAgeSeconds = SESSION_MAX_AGE_SECONDS
) {
  const jti = randomUUID();

  return new SignJWT({ kind: "session", jti })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${maxAgeSeconds}s`)
    .sign(keyFromSecret(secret));
}

export async function verifySessionToken(token: string, secret: string) {
  const { payload } = await jwtVerify(token, keyFromSecret(secret), {
    algorithms: ["HS256"]
  });

  return sessionClaimsSchema.parse(payload);
}

