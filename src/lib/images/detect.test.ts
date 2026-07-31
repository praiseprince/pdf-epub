import { describe, expect, it } from "vitest";
import { detectImage } from "./detect";

describe("image detection", () => {
  it("detects common image signatures without assuming JPEG", () => {
    expect(detectImage(Uint8Array.from([0xff, 0xd8, 0xff])).mediaType).toBe("image/jpeg");
    expect(detectImage(Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0, 0, 0, 0])).mediaType).toBe(
      "image/png"
    );
    expect(detectImage(new TextEncoder().encode("<svg></svg>")).mediaType).toBe("image/svg+xml");
  });
});

