import { describe, expect, it } from "vitest";
import { hashPin, verifyPin } from "./password";
import { signSessionToken, verifySessionToken } from "./tokens";

const secret = "test-secret-value-that-is-long-enough";

describe("PIN authentication", () => {
  it("verifies bcrypt PIN hashes", async () => {
    const hash = await hashPin("correct-horse", 4);

    await expect(verifyPin("correct-horse", hash)).resolves.toBe(true);
    await expect(verifyPin("wrong-horse", hash)).resolves.toBe(false);
  });

  it("rejects short PIN generation", async () => {
    await expect(hashPin("1234", 4)).rejects.toThrow("at least eight");
  });
});

describe("session tokens", () => {
  it("signs and verifies session tokens", async () => {
    const token = await signSessionToken(secret, 60);
    await expect(verifySessionToken(token, secret)).resolves.toMatchObject({
      kind: "session"
    });
  });

  it("rejects modified tokens", async () => {
    const token = await signSessionToken(secret, 60);
    const modified = `${token.slice(0, -1)}x`;

    await expect(verifySessionToken(modified, secret)).rejects.toThrow();
  });

  it("rejects expired tokens", async () => {
    const token = await signSessionToken(secret, -1);

    await expect(verifySessionToken(token, secret)).rejects.toThrow();
  });
});

