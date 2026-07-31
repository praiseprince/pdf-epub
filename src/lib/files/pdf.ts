export const PDF_SIGNATURE = "%PDF-";

export function hasPdfExtension(filename: string) {
  return filename.trim().toLowerCase().endsWith(".pdf");
}

export function hasPdfMimeType(type: string | null | undefined) {
  return !type || type === "application/pdf" || type === "application/x-pdf";
}

export async function fileHasPdfSignature(file: File) {
  const header = await file.slice(0, PDF_SIGNATURE.length).text();
  return header === PDF_SIGNATURE;
}

export function bufferHasPdfSignature(bytes: Uint8Array) {
  if (bytes.length < PDF_SIGNATURE.length) {
    return false;
  }

  return new TextDecoder("ascii").decode(bytes.subarray(0, PDF_SIGNATURE.length)) === PDF_SIGNATURE;
}

