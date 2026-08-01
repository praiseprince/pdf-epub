const UUID_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const SAFE_ASSET_PATTERN = "[a-zA-Z0-9._/-]+";
const JOB_PATH_RE = new RegExp(
  `^tmp/(${UUID_PATTERN})/(source\\.pdf|result\\.epub|finalize-state\\.json|text/${SAFE_ASSET_PATTERN}|assets/${SAFE_ASSET_PATTERN})$`
);

export function sourcePdfPath(jobId: string) {
  return `tmp/${jobId}/source.pdf`;
}

export function resultEpubPath(jobId: string) {
  return `tmp/${jobId}/result.epub`;
}

export function finalizeStatePath(jobId: string) {
  return `tmp/${jobId}/finalize-state.json`;
}

export function stagedChapterPath(jobId: string, filename: string) {
  return `tmp/${jobId}/${filename}`;
}

export function stagedResourcePath(jobId: string, href: string) {
  return `tmp/${jobId}/${href}`;
}

export function isValidJobBlobPath(pathname: string) {
  if (pathname.includes("..") || pathname.startsWith("/") || pathname.includes("\\")) {
    return false;
  }

  return JOB_PATH_RE.test(pathname);
}

export function jobIdFromPath(pathname: string) {
  const match = JOB_PATH_RE.exec(pathname);
  return match?.[1] ?? null;
}

export function assertPathBelongsToJob(pathname: string, jobId: string) {
  return isValidJobBlobPath(pathname) && jobIdFromPath(pathname) === jobId;
}
