"use client";

import type { PutBlobResult } from "@vercel/blob";
import { upload } from "@vercel/blob/client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { fileHasPdfSignature, hasPdfExtension, hasPdfMimeType } from "@/lib/files/pdf";

type UploadAuthorization = {
  jobId: string;
  inputPath: string;
  uploadToken: string;
  maxSizeBytes: number;
};

type Stage = "idle" | "uploading" | "uploaded" | "submitting" | "reading" | "building" | "ready";

type SubmitResponse = {
  jobToken: string;
  pageCount: number | null;
  stage: string;
};

type StatusResponse = {
  state: "pending" | "running" | "completed" | "failed";
  stage: string;
  progress: {
    totalPages: number;
    extractedPages: number;
  } | null;
  error?: string;
};

type BuildProgress = {
  label: string;
  processed: number;
  total: number;
};

type FinalizeResponse =
  | {
      state: "building";
      stage: string;
      progress: BuildProgress;
      warnings: string[];
    }
  | {
      state: "ready";
      stage: string;
      progress: BuildProgress;
      downloadUrl: string;
      warnings: string[];
    };

type SavedJobState = "submitted" | "running" | "building" | "ready" | "failed" | "expired";

type SavedJob = {
  id: string;
  jobToken: string;
  filename: string;
  title?: string;
  author?: string;
  createdAt: number;
  expiresAt: number;
  updatedAt: number;
  state: SavedJobState;
  stage: string;
  pageCount: number | null;
  progress: StatusResponse["progress"];
  buildProgress: BuildProgress | null;
  downloadUrl?: string;
  warnings: string[];
  error?: string;
};

type SavedJobFallback = {
  [Property in keyof SavedJob]?: SavedJob[Property] | undefined;
};

type ClientJobClaims = {
  jobId: string;
  originalFilename: string;
  title?: string;
  author?: string;
  createdAt: number;
  expiresAt: number;
};

const SAVED_JOBS_KEY = "pdf-epub:saved-jobs:v1";
const ACTIVE_JOB_TOKEN_KEY = "pdf-epub:active-job-token:v1";
const LEGACY_ACTIVE_JOB_TOKEN_KEY = "active-job-token";
const SAVED_JOB_LIMIT = 20;
const ONE_HOUR_MS = 60 * 60 * 1000;
const SAVED_JOB_STATES: SavedJobState[] = ["submitted", "running", "building", "ready", "failed", "expired"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSavedJobState(value: unknown): value is SavedJobState {
  return typeof value === "string" && SAVED_JOB_STATES.includes(value as SavedJobState);
}

function normalizeBase64Url(value: string) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  return normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
}

function decodeJobClaims(jobToken: string): ClientJobClaims | null {
  const [, payload] = jobToken.split(".");
  if (!payload || typeof window === "undefined") {
    return null;
  }

  try {
    const binary = window.atob(normalizeBase64Url(payload));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }

    const parsed = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
    if (!isRecord(parsed)) {
      return null;
    }

    if (typeof parsed.jobId !== "string" || typeof parsed.originalFilename !== "string") {
      return null;
    }

    const now = Date.now();
    return {
      jobId: parsed.jobId,
      originalFilename: parsed.originalFilename,
      ...(typeof parsed.title === "string" ? { title: parsed.title } : {}),
      ...(typeof parsed.author === "string" ? { author: parsed.author } : {}),
      createdAt: typeof parsed.createdAt === "number" ? parsed.createdAt : now,
      expiresAt: typeof parsed.expiresAt === "number" ? parsed.expiresAt : now + ONE_HOUR_MS
    };
  } catch {
    return null;
  }
}

function parseProgress(value: unknown): StatusResponse["progress"] {
  if (!isRecord(value)) {
    return null;
  }

  if (typeof value.totalPages !== "number" || typeof value.extractedPages !== "number") {
    return null;
  }

  return {
    totalPages: value.totalPages,
    extractedPages: value.extractedPages
  };
}

function parseBuildProgress(value: unknown): BuildProgress | null {
  if (!isRecord(value)) {
    return null;
  }

  if (
    typeof value.label !== "string" ||
    typeof value.processed !== "number" ||
    typeof value.total !== "number"
  ) {
    return null;
  }

  return {
    label: value.label,
    processed: value.processed,
    total: value.total
  };
}

function savedJobFromToken(jobToken: string, fallback: SavedJobFallback = {}): SavedJob {
  const claims = decodeJobClaims(jobToken);
  const now = Date.now();
  const title = claims?.title ?? fallback.title;
  const author = claims?.author ?? fallback.author;
  const downloadUrl = fallback.downloadUrl;
  const error = fallback.error;

  return {
    id: claims?.jobId ?? fallback.id ?? jobToken.slice(-18),
    jobToken,
    filename: claims?.originalFilename ?? fallback.filename ?? "PDF conversion",
    ...(title ? { title } : {}),
    ...(author ? { author } : {}),
    createdAt: claims?.createdAt ?? fallback.createdAt ?? now,
    expiresAt: claims?.expiresAt ?? fallback.expiresAt ?? now + ONE_HOUR_MS,
    updatedAt: fallback.updatedAt ?? now,
    state: fallback.state ?? "submitted",
    stage: fallback.stage ?? "Submitted to PaddleOCR",
    pageCount: fallback.pageCount ?? null,
    progress: fallback.progress ?? null,
    buildProgress: fallback.buildProgress ?? null,
    ...(downloadUrl ? { downloadUrl } : {}),
    warnings: fallback.warnings ?? [],
    ...(error ? { error } : {})
  };
}

function normalizeSavedJob(value: unknown): SavedJob | null {
  if (!isRecord(value) || typeof value.jobToken !== "string") {
    return null;
  }

  return savedJobFromToken(value.jobToken, {
    id: typeof value.id === "string" ? value.id : undefined,
    filename: typeof value.filename === "string" ? value.filename : undefined,
    title: typeof value.title === "string" ? value.title : undefined,
    author: typeof value.author === "string" ? value.author : undefined,
    createdAt: typeof value.createdAt === "number" ? value.createdAt : undefined,
    expiresAt: typeof value.expiresAt === "number" ? value.expiresAt : undefined,
    updatedAt: typeof value.updatedAt === "number" ? value.updatedAt : undefined,
    state: isSavedJobState(value.state) ? value.state : undefined,
    stage: typeof value.stage === "string" ? value.stage : undefined,
    pageCount: typeof value.pageCount === "number" ? value.pageCount : null,
    progress: parseProgress(value.progress),
    buildProgress: parseBuildProgress(value.buildProgress),
    downloadUrl: typeof value.downloadUrl === "string" ? value.downloadUrl : undefined,
    warnings: Array.isArray(value.warnings) ? value.warnings.filter((warning) => typeof warning === "string") : [],
    error: typeof value.error === "string" ? value.error : undefined
  });
}

function pruneSavedJobs(jobs: SavedJob[], now = Date.now()) {
  const seen = new Set<string>();
  return jobs
    .filter((job) => job.expiresAt > now)
    .filter((job) => {
      if (seen.has(job.jobToken)) {
        return false;
      }
      seen.add(job.jobToken);
      return true;
    })
    .sort((left, right) => right.updatedAt - left.updatedAt)
    .slice(0, SAVED_JOB_LIMIT);
}

function readSavedJobsFromStorage() {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(SAVED_JOBS_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return pruneSavedJobs(parsed.map(normalizeSavedJob).filter((job): job is SavedJob => Boolean(job)));
  } catch {
    return [];
  }
}

function writeSavedJobsToStorage(jobs: SavedJob[]) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    if (jobs.length === 0) {
      window.localStorage.removeItem(SAVED_JOBS_KEY);
      return;
    }
    window.localStorage.setItem(SAVED_JOBS_KEY, JSON.stringify(jobs));
  } catch {
    // Best effort only: local conversion still works without browser storage.
  }
}

function readActiveJobToken() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(ACTIVE_JOB_TOKEN_KEY) ?? window.sessionStorage.getItem(LEGACY_ACTIVE_JOB_TOKEN_KEY) ?? "";
}

function storeActiveJobToken(jobToken: string) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(ACTIVE_JOB_TOKEN_KEY, jobToken);
    window.sessionStorage.setItem(LEGACY_ACTIVE_JOB_TOKEN_KEY, jobToken);
  } catch {
    // Best effort only.
  }
}

function clearActiveJobToken() {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.removeItem(ACTIVE_JOB_TOKEN_KEY);
    window.sessionStorage.removeItem(LEGACY_ACTIVE_JOB_TOKEN_KEY);
  } catch {
    // Best effort only.
  }
}

function formatSavedJobTime(timestamp: number) {
  return new Date(timestamp).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

function savedJobStateLabel(state: SavedJobState) {
  switch (state) {
    case "submitted":
      return "Submitted";
    case "running":
      return "Reading";
    case "building":
      return "Building";
    case "ready":
      return "Ready";
    case "failed":
      return "Failed";
    case "expired":
      return "Expired";
  }
}

export function ConvertClient() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const uploadTokenRef = useRef("");
  const jobTokenRef = useRef("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState("");
  const [uploadedBlob, setUploadedBlob] = useState<PutBlobResult | null>(null);
  const [uploadToken, setUploadToken] = useState("");
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [paddleProgress, setPaddleProgress] = useState<StatusResponse["progress"]>(null);
  const [buildProgress, setBuildProgress] = useState<BuildProgress | null>(null);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [jobToken, setJobToken] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [savedJobs, setSavedJobs] = useState<SavedJob[]>([]);
  const [jobsOpen, setJobsOpen] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      const jobs = readSavedJobsFromStorage();
      setSavedJobs(jobs);
      writeSavedJobsToStorage(jobs);
      setJobsOpen(Boolean(readActiveJobToken() && jobs.length > 0));
    });
  }, []);

  function upsertSavedJob(nextJobToken: string, patch: SavedJobFallback = {}) {
    setSavedJobs((current) => {
      const existing = current.find((job) => job.jobToken === nextJobToken);
      const nextJob = savedJobFromToken(nextJobToken, {
        ...existing,
        ...patch,
        updatedAt: Date.now()
      });
      const next = pruneSavedJobs([nextJob, ...current.filter((job) => job.jobToken !== nextJobToken)]);
      writeSavedJobsToStorage(next);
      return next;
    });
  }

  function removeSavedJob(nextJobToken: string) {
    setSavedJobs((current) => {
      const next = pruneSavedJobs(current.filter((job) => job.jobToken !== nextJobToken));
      writeSavedJobsToStorage(next);
      return next;
    });
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  async function chooseFile(nextFile: File | null) {
    setError("");
    setUploadedBlob(null);
    setPageCount(null);
    setPaddleProgress(null);
    setBuildProgress(null);
    setDownloadUrl("");
    setJobToken("");
    setUploadToken("");
    jobTokenRef.current = "";
    uploadTokenRef.current = "";
    clearActiveJobToken();
    setWarnings([]);
    setStage("idle");

    if (!nextFile) {
      setFile(null);
      return;
    }

    if (!hasPdfExtension(nextFile.name) || !hasPdfMimeType(nextFile.type)) {
      setFile(null);
      setError("This file is not a valid PDF.");
      return;
    }

    if (!(await fileHasPdfSignature(nextFile))) {
      setFile(null);
      setError("This file is not a valid PDF.");
      return;
    }

    setFile(nextFile);
    if (!title) {
      setTitle(nextFile.name.replace(/\.pdf$/i, ""));
    }
  }

  async function convert() {
    if (!file) {
      setError("Choose a PDF before converting.");
      return;
    }

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const { signal } = controller;

    setError("");
    setStage("uploading");
    setUploadedBlob(null);

    try {
      const authResponse = await fetch("/api/upload/authorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          filename: file.name,
          size: file.size,
          contentType: file.type || "application/pdf"
        })
      });

      if (!authResponse.ok) {
        const body = (await authResponse.json().catch(() => null)) as { error?: string } | null;
        setStage("idle");
        setError(body?.error ?? "Upload failed.");
        return;
      }

      const authorization = (await authResponse.json()) as UploadAuthorization;
      uploadTokenRef.current = authorization.uploadToken;
      setUploadToken(authorization.uploadToken);

      const blob = await upload(authorization.inputPath, file, {
        access: "private",
        contentType: "application/pdf",
        multipart: file.size > 8 * 1024 * 1024,
        abortSignal: signal,
        handleUploadUrl: "/api/upload/authorize",
        clientPayload: JSON.stringify({ uploadToken: authorization.uploadToken })
      });

      setUploadedBlob(blob);
      setStage("submitting");

      const submitResponse = await fetch("/api/jobs/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          uploadToken: authorization.uploadToken,
          inputPath: authorization.inputPath,
          title,
          author
        })
      });

      if (!submitResponse.ok) {
        const body = (await submitResponse.json().catch(() => null)) as { error?: string } | null;
        setStage("uploaded");
        setError(body?.error ?? "Document parsing failed.");
        return;
      }

      const submitted = (await submitResponse.json()) as SubmitResponse;
      setPageCount(submitted.pageCount);
      setJobToken(submitted.jobToken);
      jobTokenRef.current = submitted.jobToken;
      storeActiveJobToken(submitted.jobToken);
      upsertSavedJob(submitted.jobToken, {
        filename: file.name,
        title,
        author,
        pageCount: submitted.pageCount,
        progress: null,
        buildProgress: null,
        state: "submitted",
        stage: submitted.stage,
        warnings: []
      });
      await pollStatus(submitted.jobToken, signal);
    } catch {
      if (signal.aborted) {
        return;
      }
      setStage("idle");
      setError("Upload failed.");
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }

  async function waitForPoll(delayMs: number, signal: AbortSignal) {
    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, delayMs);
      signal.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          resolve();
        },
        { once: true }
      );
    });
  }

  async function pollStatus(jobToken: string, signal: AbortSignal) {
    setStage("reading");
    setBuildProgress(null);
    upsertSavedJob(jobToken, {
      state: "running",
      stage: "Reading document",
      error: undefined
    });
    let elapsedMs = 0;

    while (true) {
      const response = await fetch("/api/jobs/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({ jobToken })
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        const publicError = body?.error ?? "Document parsing failed.";
        setError(publicError);
        upsertSavedJob(jobToken, {
          state: response.status === 401 ? "expired" : "failed",
          stage: response.status === 401 ? "Expired" : "Document parsing failed",
          error: publicError
        });
        return;
      }

      const status = (await response.json()) as StatusResponse;
      setPaddleProgress(status.progress);
      upsertSavedJob(jobToken, {
        state: status.state === "pending" ? "submitted" : "running",
        stage: status.stage,
        progress: status.progress,
        error: undefined
      });

      if (status.state === "completed") {
        await finalize(jobToken, signal);
        return;
      }

      if (status.state === "failed") {
        const publicError = status.error || "Document parsing failed.";
        setError(publicError);
        upsertSavedJob(jobToken, {
          state: "failed",
          stage: "Document parsing failed",
          error: publicError
        });
        return;
      }

      const delayMs = elapsedMs < 60_000 ? 5_000 : 10_000;
      await waitForPoll(delayMs, signal);
      if (signal.aborted) {
        return;
      }
      elapsedMs += delayMs;
    }
  }

  async function finalize(jobToken: string, signal: AbortSignal) {
    setStage("building");
    upsertSavedJob(jobToken, {
      state: "building",
      stage: "Building EPUB",
      error: undefined
    });

    while (true) {
      const response = await fetch("/api/jobs/finalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({ jobToken })
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        const publicError = body?.error ?? "EPUB generation failed.";
        setError(publicError);
        upsertSavedJob(jobToken, {
          state: response.status === 401 ? "expired" : "failed",
          stage: response.status === 401 ? "Expired" : "EPUB generation failed",
          error: publicError
        });
        return;
      }

      const body = (await response.json()) as FinalizeResponse;
      setWarnings(body.warnings);
      setBuildProgress(body.progress);

      if (body.state === "ready") {
        setDownloadUrl(body.downloadUrl);
        setStage("ready");
        upsertSavedJob(jobToken, {
          state: "ready",
          stage: "Ready to download",
          buildProgress: body.progress,
          downloadUrl: body.downloadUrl,
          warnings: body.warnings,
          error: undefined
        });
        return;
      }

      upsertSavedJob(jobToken, {
        state: "building",
        stage: body.stage,
        buildProgress: body.progress,
        warnings: body.warnings,
        error: undefined
      });

      await waitForPoll(800, signal);
      if (signal.aborted) {
        return;
      }
    }
  }

  async function refreshDownloadUrl(nextJobToken: string, signal: AbortSignal) {
    const response = await fetch(`/api/download-url?jobToken=${encodeURIComponent(nextJobToken)}`, { signal });
    if (!response.ok) {
      return "";
    }

    const body = (await response.json()) as { downloadUrl: string };
    return body.downloadUrl;
  }

  function startEpubDownload(nextDownloadUrl: string) {
    const anchor = document.createElement("a");
    anchor.href = nextDownloadUrl;
    anchor.download = "";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
  }

  async function downloadEpubForJob(nextJobToken: string, savedJob?: SavedJob) {
    const controller = new AbortController();
    const { signal } = controller;
    setError("");

    try {
      const freshDownloadUrl = await refreshDownloadUrl(nextJobToken, signal);
      if (!freshDownloadUrl) {
        setError("The EPUB download is not ready. Check the saved job again.");
        return;
      }

      if (savedJob) {
        setJobToken(savedJob.jobToken);
        jobTokenRef.current = savedJob.jobToken;
        storeActiveJobToken(savedJob.jobToken);
        setTitle(savedJob.title ?? savedJob.filename.replace(/\.pdf$/i, ""));
        setAuthor(savedJob.author ?? "");
        setPageCount(savedJob.pageCount);
        setPaddleProgress(savedJob.progress);
        setBuildProgress(savedJob.buildProgress);
      setWarnings(savedJob.warnings);
        setStage("ready");
      }

      setDownloadUrl(freshDownloadUrl);
      upsertSavedJob(nextJobToken, {
        state: "ready",
        stage: "Ready to download",
        buildProgress: { label: "EPUB ready", processed: 1, total: 1 },
        downloadUrl: freshDownloadUrl,
        error: undefined
      });
      startEpubDownload(freshDownloadUrl);
      scheduleCleanupAfterDownload(nextJobToken);
    } catch {
      if (!signal.aborted) {
        setError("The EPUB download is not available.");
      }
    }
  }

  async function resumeSavedJob(savedJob: SavedJob) {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const { signal } = controller;

    setJobsOpen(true);
    setError("");
    setFile(null);
    setUploadedBlob(null);
    setUploadToken("");
    uploadTokenRef.current = "";
    setTitle(savedJob.title ?? savedJob.filename.replace(/\.pdf$/i, ""));
    setAuthor(savedJob.author ?? "");
    setPageCount(savedJob.pageCount);
    setPaddleProgress(savedJob.progress);
    setBuildProgress(savedJob.buildProgress);
    setWarnings(savedJob.warnings);
    setJobToken(savedJob.jobToken);
    jobTokenRef.current = savedJob.jobToken;
    storeActiveJobToken(savedJob.jobToken);

    try {
      if (savedJob.state === "ready") {
        setStage("ready");
        const existingDownloadUrl = await refreshDownloadUrl(savedJob.jobToken, signal);
        if (existingDownloadUrl) {
          setDownloadUrl(existingDownloadUrl);
          upsertSavedJob(savedJob.jobToken, {
            state: "ready",
            stage: "Ready to download",
            buildProgress: { label: "EPUB ready", processed: 1, total: 1 },
            downloadUrl: existingDownloadUrl,
            error: undefined
          });
          return;
        }
      }

      setDownloadUrl("");
      await pollStatus(savedJob.jobToken, signal);
    } catch {
      if (!signal.aborted) {
        const publicError = "Could not check this saved job.";
        setError(publicError);
        upsertSavedJob(savedJob.jobToken, {
          state: "failed",
          stage: publicError,
          error: publicError
        });
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }

  async function deleteSavedJob(job: SavedJob) {
    abortControllerRef.current?.abort();

    await fetch("/api/jobs/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobToken: job.jobToken })
    }).catch(() => undefined);

    removeSavedJob(job.jobToken);
    if (job.jobToken === jobTokenRef.current || job.jobToken === jobToken || job.jobToken === readActiveJobToken()) {
      clearActiveJobToken();
      setUploadedBlob(null);
      setPageCount(null);
      setPaddleProgress(null);
      setBuildProgress(null);
      setDownloadUrl("");
      setJobToken("");
      jobTokenRef.current = "";
      setWarnings([]);
      setStage("idle");
    }
  }

  async function deleteTemporaryFiles() {
    const token = jobTokenRef.current || jobToken || readActiveJobToken();
    const uploadToken = uploadTokenRef.current;
    if (!token && !uploadToken) {
      return;
    }

    await fetch("/api/jobs/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(token ? { jobToken: token } : { uploadToken })
    });
  }

  async function deleteNow() {
    abortControllerRef.current?.abort();
    const token = jobTokenRef.current || jobToken || readActiveJobToken();
    await deleteTemporaryFiles();
    if (token) {
      removeSavedJob(token);
    }
    clearActiveJobToken();
    setPageCount(null);
    setPaddleProgress(null);
    setBuildProgress(null);
    setDownloadUrl("");
    setJobToken("");
    setUploadToken("");
    jobTokenRef.current = "";
    uploadTokenRef.current = "";
    setWarnings([]);
    setStage("idle");
    setUploadedBlob(null);
    setFile(null);
  }

  async function cancelConversion() {
    abortControllerRef.current?.abort();
    const token = jobTokenRef.current || jobToken || readActiveJobToken();
    await deleteTemporaryFiles().catch(() => undefined);
    if (token) {
      removeSavedJob(token);
    }
    clearActiveJobToken();
    setUploadedBlob(null);
    setPageCount(null);
    setPaddleProgress(null);
    setBuildProgress(null);
    setDownloadUrl("");
    setJobToken("");
    setUploadToken("");
    jobTokenRef.current = "";
    uploadTokenRef.current = "";
    setWarnings([]);
    setStage("idle");
  }

  function scheduleCleanupAfterDownload(nextJobToken = jobTokenRef.current || jobToken || readActiveJobToken()) {
    setTimeout(() => {
      const savedJob = savedJobs.find((job) => job.jobToken === nextJobToken);
      if (savedJob) {
        void deleteSavedJob(savedJob);
        return;
      }
      void deleteNow();
    }, 10_000);
  }

  const isConverting = ["uploading", "submitting", "reading", "building"].includes(stage);

  return (
    <section className="panel stack" aria-labelledby="convert-title">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <p className="kicker">Smart EPUB</p>
          <h1 id="convert-title">PDF to EPUB</h1>
          <p className="notice">The PDF is temporarily sent to Baidu PaddleOCR for document parsing.</p>
        </div>
        <button className="button secondary" type="button" onClick={logout}>
          Logout
        </button>
        <button className="button secondary" type="button" onClick={() => setJobsOpen((open) => !open)}>
          Saved jobs{savedJobs.length > 0 ? ` (${savedJobs.length})` : ""}
        </button>
      </div>

      {jobsOpen ? (
        <section className="jobs-panel" aria-label="Saved jobs">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>Saved jobs</h2>
            <button className="button secondary compact" type="button" onClick={() => setJobsOpen(false)}>
              Close
            </button>
          </div>
          {savedJobs.length === 0 ? (
            <p className="notice">No saved jobs.</p>
          ) : (
            <ul className="jobs-list">
              {savedJobs.map((savedJob) => (
                <li className="job-item" key={savedJob.id}>
                  <div className="job-title-row">
                    <div>
                      <strong>{savedJob.title || savedJob.filename}</strong>
                      <p className="job-meta">{savedJob.filename}</p>
                    </div>
                    <span className={`job-state ${savedJob.state}`}>{savedJobStateLabel(savedJob.state)}</span>
                  </div>
                  <p className="job-meta">
                    Updated {formatSavedJobTime(savedJob.updatedAt)}. Expires {formatSavedJobTime(savedJob.expiresAt)}.
                  </p>
                  {savedJob.progress ? (
                    <p className="job-meta">
                      PaddleOCR has read {savedJob.progress.extractedPages} of {savedJob.progress.totalPages} pages.
                    </p>
                  ) : null}
                  {savedJob.buildProgress ? (
                    <p className="job-meta">
                      {savedJob.buildProgress.label}: {savedJob.buildProgress.processed} of {savedJob.buildProgress.total}.
                    </p>
                  ) : null}
                  {savedJob.error ? <p className="error">{savedJob.error}</p> : null}
                  <div className="row job-actions">
                    <button
                      className="button secondary compact"
                      type="button"
                      disabled={isConverting}
                      onClick={() => void resumeSavedJob(savedJob)}
                    >
                      {savedJob.state === "ready" ? "Refresh link" : "Check"}
                    </button>
                    {savedJob.state === "ready" || savedJob.downloadUrl ? (
                      <button
                        className="button compact"
                        type="button"
                        disabled={isConverting}
                        onClick={() => void downloadEpubForJob(savedJob.jobToken, savedJob)}
                      >
                        Download
                      </button>
                    ) : null}
                    <button
                      className="button danger compact"
                      type="button"
                      disabled={isConverting}
                      onClick={() => void deleteSavedJob(savedJob)}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <div
        className={`dropzone${isDragging ? " active" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          void chooseFile(event.dataTransfer.files.item(0));
        }}
      >
        <div>
          <strong>Select or drag in a PDF</strong>
          <p className="notice">The file uploads directly to private Vercel Blob storage.</p>
          {file ? <p className="file-name">{file.name}</p> : null}
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(event) => void chooseFile(event.currentTarget.files?.item(0) ?? null)}
      />

      <div className="row">
        <label className="field" style={{ flex: "1 1 240px" }}>
          <span>Title</span>
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Detected title"
          />
        </label>
        <label className="field" style={{ flex: "1 1 200px" }}>
          <span>Author</span>
          <input
            className="input"
            value={author}
            onChange={(event) => setAuthor(event.target.value)}
            placeholder="Optional"
          />
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {uploadedBlob && stage === "uploaded" ? (
        <p className="success">PDF uploaded. Waiting to submit to PaddleOCR.</p>
      ) : null}
      {pageCount ? <p className="notice">Validated {pageCount} page PDF.</p> : null}
      {paddleProgress ? (
        <p className="notice">
          PaddleOCR has read {paddleProgress.extractedPages} of {paddleProgress.totalPages} pages.
        </p>
      ) : null}
      {buildProgress ? (
        <p className="notice">
          {buildProgress.label}: {buildProgress.processed} of {buildProgress.total}.
        </p>
      ) : null}
      {stage === "ready" ? (
        <p className="success">EPUB ready to download.</p>
      ) : null}
      {warnings.length > 0 ? <p className="notice">{warnings.length} conversion warning(s).</p> : null}

      <ul className="progress" aria-label="Conversion progress">
        <li className={["uploading", "submitting", "reading", "building", "ready"].includes(stage) ? "done" : ""}>
          <span className="dot" /> Uploading PDF
        </li>
        <li className={stage === "submitting" ? "current" : ["reading", "building", "ready"].includes(stage) ? "done" : ""}>
          <span className="dot" /> Sending to document parser
        </li>
        <li className={stage === "reading" ? "current" : ["building", "ready"].includes(stage) ? "done" : ""}>
          <span className="dot" /> Reading document
        </li>
        <li className={stage === "building" || stage === "ready" ? "done" : ""}>
          <span className="dot" /> Processing formulas and figures
        </li>
        <li className={stage === "building" ? "current" : stage === "ready" ? "done" : ""}>
          <span className="dot" /> Building EPUB
        </li>
        <li className={stage === "ready" ? "current" : ""}>
          <span className="dot" /> Ready to download
        </li>
      </ul>

      <div className="row">
        <button
          className="button"
          type="button"
          disabled={!file || ["uploading", "submitting", "reading", "building"].includes(stage)}
          onClick={convert}
        >
          {stage === "uploading"
            ? "Uploading PDF"
            : stage === "submitting"
              ? "Sending to parser"
            : stage === "reading"
                ? "Reading document"
                : stage === "building"
                  ? "Building EPUB"
                  : "Convert to EPUB"}
        </button>
        {downloadUrl ? (
          <button
            className="button"
            type="button"
            onClick={() => void downloadEpubForJob(jobTokenRef.current || jobToken || readActiveJobToken())}
          >
            Download EPUB
          </button>
        ) : null}
        {downloadUrl ? (
          <button className="button danger" type="button" onClick={() => void deleteNow()}>
            Delete now
          </button>
        ) : null}
        <button
          className="button secondary"
          type="button"
          disabled={!file && !jobToken && !downloadUrl && !uploadToken}
          onClick={() =>
            isConverting || jobToken || downloadUrl || uploadToken
              ? void cancelConversion()
              : void chooseFile(null)
          }
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
