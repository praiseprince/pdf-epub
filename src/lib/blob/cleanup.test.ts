import { describe, expect, it } from "vitest";
import { expiredTmpPathnames } from "./cleanup";

describe("temporary Blob cleanup", () => {
  it("selects only expired app tmp namespace objects", () => {
    const old = new Date("2026-01-01T00:00:00Z");
    const fresh = new Date("2026-01-01T01:30:00Z");
    const now = new Date("2026-01-01T02:00:00Z").getTime();

    const expired = expiredTmpPathnames(
      [
        {
          pathname: "tmp/123e4567-e89b-12d3-a456-426614174000/source.pdf",
          uploadedAt: old,
          size: 1,
          url: "",
          downloadUrl: "",
          etag: ""
        },
        {
          pathname: "tmp/123e4567-e89b-12d3-a456-426614174000/result.epub",
          uploadedAt: fresh,
          size: 1,
          url: "",
          downloadUrl: "",
          etag: ""
        },
        {
          pathname: "other/123/source.pdf",
          uploadedAt: old,
          size: 1,
          url: "",
          downloadUrl: "",
          etag: ""
        },
        {
          pathname: "tmp/123e4567-e89b-12d3-a456-426614174000/../source.pdf",
          uploadedAt: old,
          size: 1,
          url: "",
          downloadUrl: "",
          etag: ""
        }
      ],
      now
    );

    expect(expired).toEqual(["tmp/123e4567-e89b-12d3-a456-426614174000/source.pdf"]);
  });
});
