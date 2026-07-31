import sharp from "sharp";
import { maxImageSizeBytes, maxTotalAssetBytes } from "@/lib/config/limits";
import { detectImage } from "@/lib/images/detect";
import { ResourceRegistry } from "./resources";

const ALLOWED_RESOURCE_HOSTS = [
  "baidu.com",
  "bcebos.com",
  "bdstatic.com",
  "paddleocr.ai",
  "aistudio.baidu.com",
  "blob.vercel-storage.com"
];

export type PreparedImageMap = Map<string, string>;

export function isAllowedResourceUrl(value: string) {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }

  if (url.protocol !== "https:") {
    return false;
  }

  return ALLOWED_RESOURCE_HOSTS.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`));
}

async function fetchBytes(url: string) {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(30_000)
  });

  if (!response.ok) {
    throw new Error("Image resource could not be downloaded.");
  }

  const contentLength = Number.parseInt(response.headers.get("content-length") ?? "0", 10);
  if (contentLength > maxImageSizeBytes()) {
    throw new Error("Image resource exceeded the size limit.");
  }

  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > maxImageSizeBytes()) {
    throw new Error("Image resource exceeded the size limit.");
  }

  return bytes;
}

async function normalizeImage(bytes: Uint8Array) {
  const detected = detectImage(bytes);
  if (detected.extension === "bin") {
    throw new Error("Image resource is not a supported image.");
  }

  const pipeline = sharp(bytes, { limitInputPixels: 80_000_000 }).rotate();
  if (detected.extension === "jpg") {
    return {
      extension: "jpg" as const,
      mediaType: "image/jpeg",
      bytes: await pipeline.jpeg({ quality: 88, mozjpeg: true }).toBuffer()
    };
  }

  return {
    extension: "png" as const,
    mediaType: "image/png",
    bytes: await pipeline.png({ compressionLevel: 9 }).toBuffer()
  };
}

export async function prepareImageResources(
  imageReferences: Record<string, string>,
  resources: ResourceRegistry,
  warnings: string[]
): Promise<PreparedImageMap> {
  const map: PreparedImageMap = new Map();
  let totalBytes = 0;

  for (const [markdownPath, remoteUrl] of Object.entries(imageReferences)) {
    if (!isAllowedResourceUrl(remoteUrl)) {
      warnings.push("One image was skipped because its host was not allowed.");
      continue;
    }

    try {
      const original = await fetchBytes(remoteUrl);
      const normalized = await normalizeImage(original);
      totalBytes += normalized.bytes.byteLength;
      if (totalBytes > maxTotalAssetBytes()) {
        throw new Error("Image resources exceeded the total asset limit.");
      }
      const href = resources.addHashed("images", normalized.extension, normalized.mediaType, normalized.bytes);
      map.set(markdownPath, `../${href}`);
      map.set(remoteUrl, `../${href}`);
    } catch {
      warnings.push("One image could not be downloaded and was replaced with a fallback.");
    }
  }

  return map;
}

