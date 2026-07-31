import { jwtVerify, SignJWT } from "jose";
import { z } from "zod";
import { isValidJobBlobPath } from "@/lib/blob/paths";
import { jobExpirationMinutes } from "@/lib/config/limits";
import { readRequiredEnv } from "@/lib/server/env";

const encoder = new TextEncoder();

const baseTokenSchema = z.object({
  jobId: z.string().uuid(),
  inputPath: z.string().refine(isValidJobBlobPath),
  originalFilename: z.string().min(1).max(160),
  createdAt: z.number().int().positive(),
  expiresAt: z.number().int().positive()
});

export const uploadTokenSchema = baseTokenSchema.extend({
  kind: z.literal("upload"),
  size: z.number().int().positive()
});

export const jobTokenSchema = baseTokenSchema.extend({
  kind: z.literal("job"),
  paddleJobId: z.string().min(1),
  title: z.string().optional(),
  author: z.string().optional()
});

export type UploadTokenClaims = z.infer<typeof uploadTokenSchema>;
export type JobTokenClaims = z.infer<typeof jobTokenSchema>;

function keyFromSecret(secret = readRequiredEnv("JOB_TOKEN_SECRET")) {
  if (secret.length < 32) {
    throw new Error("JOB_TOKEN_SECRET must be at least 32 characters.");
  }

  return encoder.encode(secret);
}

async function signClaims(claims: UploadTokenClaims | JobTokenClaims, secret?: string) {
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(claims.expiresAt / 1000))
    .sign(keyFromSecret(secret));
}

export async function signUploadToken(
  input: Omit<UploadTokenClaims, "kind" | "createdAt" | "expiresAt">,
  secret?: string
) {
  const createdAt = Date.now();
  const expiresAt = createdAt + 15 * 60 * 1000;

  return signClaims(
    {
      ...input,
      kind: "upload",
      createdAt,
      expiresAt
    },
    secret
  );
}

export async function signJobToken(
  input: Omit<JobTokenClaims, "kind" | "createdAt" | "expiresAt">,
  secret?: string
) {
  const createdAt = Date.now();
  const expiresAt = createdAt + jobExpirationMinutes() * 60 * 1000;

  return signClaims(
    {
      ...input,
      kind: "job",
      createdAt,
      expiresAt
    },
    secret
  );
}

async function verifyToken(token: string, secret?: string) {
  const { payload } = await jwtVerify(token, keyFromSecret(secret), {
    algorithms: ["HS256"]
  });

  return payload;
}

export async function verifyUploadToken(token: string, secret?: string) {
  return uploadTokenSchema.parse(await verifyToken(token, secret));
}

export async function verifyJobToken(token: string, secret?: string) {
  return jobTokenSchema.parse(await verifyToken(token, secret));
}

