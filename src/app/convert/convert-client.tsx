"use client";

import type { PutBlobResult } from "@vercel/blob";
import { upload } from "@vercel/blob/client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
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
  pageCount: number;
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

export function ConvertClient() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState("");
  const [uploadedBlob, setUploadedBlob] = useState<PutBlobResult | null>(null);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [paddleProgress, setPaddleProgress] = useState<StatusResponse["progress"]>(null);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);

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
    setDownloadUrl("");
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

    setError("");
    setStage("uploading");
    setUploadedBlob(null);

    const authResponse = await fetch("/api/upload/authorize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

    try {
      const blob = await upload(authorization.inputPath, file, {
        access: "private",
        contentType: "application/pdf",
        handleUploadUrl: "/api/upload/authorize",
        clientPayload: JSON.stringify({ uploadToken: authorization.uploadToken })
      });

      setUploadedBlob(blob);
      setStage("submitting");

      const submitResponse = await fetch("/api/jobs/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
      sessionStorage.setItem("active-job-token", submitted.jobToken);
      await pollStatus(submitted.jobToken);
    } catch {
      setStage("idle");
      setError("Upload failed.");
    }
  }

  async function pollStatus(jobToken: string) {
    setStage("reading");
    let elapsedMs = 0;

    while (true) {
      const delayMs = elapsedMs < 60_000 ? 5_000 : 10_000;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      elapsedMs += delayMs;

      const response = await fetch("/api/jobs/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobToken })
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        setError(body?.error ?? "Document parsing failed.");
        return;
      }

      const status = (await response.json()) as StatusResponse;
      setPaddleProgress(status.progress);

      if (status.state === "completed") {
        await finalize(jobToken);
        return;
      }

      if (status.state === "failed") {
        setError(status.error || "Document parsing failed.");
        return;
      }
    }
  }

  async function finalize(jobToken: string) {
    setStage("building");
    const response = await fetch("/api/jobs/finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobToken })
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      setError(body?.error ?? "EPUB generation failed.");
      return;
    }

    const body = (await response.json()) as {
      downloadUrl: string;
      warnings: string[];
    };
    setDownloadUrl(body.downloadUrl);
    setWarnings(body.warnings);
    setStage("ready");
  }

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
      </div>

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
          <a className="button" href={downloadUrl} download>
            Download EPUB
          </a>
        ) : null}
        <button
          className="button secondary"
          type="button"
          disabled={["uploading", "submitting", "reading", "building"].includes(stage)}
          onClick={() => void chooseFile(null)}
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
