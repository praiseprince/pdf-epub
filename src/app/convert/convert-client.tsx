"use client";

export function ConvertClient() {
  return (
    <section className="panel stack" aria-labelledby="convert-title">
      <div>
        <p className="kicker">Smart EPUB</p>
        <h1 id="convert-title">PDF to EPUB</h1>
        <p className="notice">The PDF is temporarily sent to Baidu PaddleOCR for document parsing.</p>
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

