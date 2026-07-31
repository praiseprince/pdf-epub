import { describe, expect, it } from "vitest";
import { sourcePdfPath } from "@/lib/blob/paths";
import { signJobToken, signUploadToken, verifyJobToken, verifyUploadToken } from "./tokens";

const secret = "job-secret-value-that-is-long-enough";
const jobId = "123e4567-e89b-12d3-a456-426614174000";
const inputPath = sourcePdfPath(jobId);

describe("upload tokens", () => {
  it("signs and verifies minimal upload metadata", async () => {
    const token = await signUploadToken(
      {
        jobId,
        inputPath,
        originalFilename: "paper.pdf",
        size: 1024
      },
      secret
    );

    await expect(verifyUploadToken(token, secret)).resolves.toMatchObject({
      kind: "upload",
      jobId,
      inputPath,
      originalFilename: "paper.pdf"
    });
  });

  it("rejects tampered upload tokens", async () => {
    const token = await signUploadToken(
      {
        jobId,
        inputPath,
        originalFilename: "paper.pdf",
        size: 1024
      },
      secret
    );

    const [header, payload, signature] = token.split(".");
    if (!header || !payload || !signature) {
      throw new Error("Expected a compact JWT.");
    }
    const tamperedPayload = `${payload.slice(0, -1)}${payload.endsWith("A") ? "B" : "A"}`;

    await expect(verifyUploadToken(`${header}.${tamperedPayload}.${signature}`, secret)).rejects.toThrow();
  });
});

describe("job tokens", () => {
  it("signs and verifies PaddleOCR job metadata", async () => {
    const token = await signJobToken(
      {
        jobId,
        inputPath,
        originalFilename: "paper.pdf",
        paddleJobId: "paddle-job-1",
        title: "Paper",
        author: "Ada"
      },
      secret
    );

    await expect(verifyJobToken(token, secret)).resolves.toMatchObject({
      kind: "job",
      paddleJobId: "paddle-job-1",
      title: "Paper"
    });
  });
});
