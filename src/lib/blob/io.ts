import { get } from "@vercel/blob";

export async function readPrivateBlobBuffer(pathname: string, maxBytes: number) {
  const result = await get(pathname, {
    access: "private",
    useCache: false
  });

  if (!result || result.statusCode !== 200) {
    throw new Error("The temporary file has already been deleted.");
  }

  if (result.blob.size > maxBytes) {
    throw new Error("This PDF exceeds the configured size limit.");
  }

  const chunks: Uint8Array[] = [];
  let received = 0;
  const reader = result.stream.getReader();

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    received += value.byteLength;
    if (received > maxBytes) {
      throw new Error("This PDF exceeds the configured size limit.");
    }
    chunks.push(value);
  }

  const out = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return out;
}

