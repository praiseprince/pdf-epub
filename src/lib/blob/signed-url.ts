import { issueSignedToken, presignUrl } from "@vercel/blob";

export async function createSignedGetUrl(pathname: string, validForMs = 60 * 60 * 1000) {
  const validUntil = Date.now() + validForMs;
  const token = await issueSignedToken({
    pathname,
    operations: ["get"],
    validUntil
  });

  const { presignedUrl } = await presignUrl(token, {
    operation: "get",
    pathname,
    access: "private",
    validUntil,
    useCache: false
  });

  return presignedUrl;
}

