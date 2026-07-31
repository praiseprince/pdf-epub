const SAFE_FILENAME_CHARS = /[^a-zA-Z0-9._ -]/g;

export function sanitizeFilename(filename: string) {
  const basename = filename.split(/[\\/]/).pop() ?? "document.pdf";
  const cleaned = basename.replace(SAFE_FILENAME_CHARS, "_").replace(/\s+/g, " ").trim();
  const withoutTraversal = cleaned.replace(/\.\.+/g, ".");
  const limited = withoutTraversal.slice(0, 120).replace(/^\.+/, "");

  return limited || "document.pdf";
}

export function sanitizeMetadataText(value: string | null | undefined, fallback = "") {
  if (!value) {
    return fallback;
  }

  return value
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/[<>]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 240);
}

