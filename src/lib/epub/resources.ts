import { createHash } from "node:crypto";

export type EpubResource = {
  href: string;
  mediaType: string;
  content: Uint8Array | string;
};

export class ResourceRegistry {
  private readonly resources = new Map<string, EpubResource>();

  addHashed(prefix: string, extension: string, mediaType: string, content: Uint8Array | string) {
    const bytes = typeof content === "string" ? Buffer.from(content) : Buffer.from(content);
    const hash = createHash("sha256").update(bytes).digest("hex").slice(0, 24);
    const href = `assets/${prefix}/${hash}.${extension}`;

    if (!this.resources.has(href)) {
      this.resources.set(href, { href, mediaType, content });
    }

    return href;
  }

  all() {
    return [...this.resources.values()];
  }
}

