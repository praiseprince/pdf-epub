"use client";

import { useRouter } from "next/navigation";

export function ConvertClient() {
  const router = useRouter();

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
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
      <div className="dropzone">
        <div>
          <strong>Converter controls are being initialized.</strong>
          <p className="notice">Upload, progress, download, and deletion controls land in the next patch.</p>
        </div>
      </div>
    </section>
  );
}
