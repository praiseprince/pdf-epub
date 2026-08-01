import { BlobNotFoundError, get, head } from "@vercel/blob";

async function getPrivateBlob(pathname: string) {
  const result = await get(pathname, {
    access: "private",
    useCache: false
  });

  if (!result || result.statusCode !== 200) {
    throw new Error("The temporary file has already been deleted.");
  }

  return result;
}

export async function readPrivateBlobBuffer(pathname: string, maxBytes: number) {
  const result = await getPrivateBlob(pathname);

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

export async function readPrivateBlobText(pathname: string, maxBytes: number) {
  return new TextDecoder().decode(await readPrivateBlobBuffer(pathname, maxBytes));
}

export async function readPrivateBlobPrefix(pathname: string, maxBytes: number) {
  const result = await getPrivateBlob(pathname);
  const reader = result.stream.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;

  while (received < maxBytes) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    const remaining = maxBytes - received;
    const chunk = value.byteLength > remaining ? value.subarray(0, remaining) : value;
    chunks.push(chunk);
    received += chunk.byteLength;
  }

  await reader.cancel().catch(() => undefined);

  const out = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return out;
}

export async function getPrivateBlobStream(pathname: string) {
  return getPrivateBlob(pathname);
}

export async function headPrivateBlob(pathname: string) {
  try {
    return await head(pathname);
  } catch (error) {
    if (error instanceof BlobNotFoundError) {
      throw new Error("The temporary file has already been deleted.");
    }
    throw error;
  }
}
