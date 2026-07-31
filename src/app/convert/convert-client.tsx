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

type Stage = "idle" | "uploading" | "uploaded";

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

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  async function chooseFile(nextFile: File | null) {
    setError("");
    setUploadedBlob(null);
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
      setStage("uploaded");
      sessionStorage.setItem(
        "active-upload",
        JSON.stringify({
          jobId: authorization.jobId,
          inputPath: authorization.inputPath,
          uploadToken: authorization.uploadToken,
          title,
          author
        })
      );
    } catch {
      setStage("idle");
      setError("Upload failed.");
    }
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
      {uploadedBlob ? <p className="success">PDF uploaded. Document parsing connects next.</p> : null}

      <ul className="progress" aria-label="Conversion progress">
        <li className={stage === "uploading" || stage === "uploaded" ? "current" : ""}>
          <span className="dot" /> Uploading PDF
        </li>
        <li>
          <span className="dot" /> Sending to document parser
        </li>
        <li>
          <span className="dot" /> Reading document
        </li>
        <li>
          <span className="dot" /> Processing formulas and figures
        </li>
        <li>
          <span className="dot" /> Building EPUB
        </li>
        <li>
          <span className="dot" /> Ready to download
        </li>
      </ul>

      <div className="row">
        <button className="button" type="button" disabled={!file || stage === "uploading"} onClick={convert}>
          {stage === "uploading" ? "Uploading PDF" : "Convert to EPUB"}
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={stage === "uploading"}
          onClick={() => void chooseFile(null)}
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
