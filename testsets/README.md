# Conversion Test Set

This directory defines a reproducible local corpus for exercising PDF-to-EPUB
conversion quality. The repository commits only the manifest and scripts; the
downloaded/generated PDFs are ignored under `testsets/pdfs/`.

Run:

```sh
npm run prepare-testset
```

The corpus intentionally covers:

- two-column research papers
- diagram- and image-heavy papers
- equation-heavy papers
- chart-heavy papers
- online HTML articles printed to PDF
- image-only scanned-like PDFs

The source documents are fetched from public URLs for local testing. Review the
source terms before redistributing downloaded files. Do not commit private PDFs,
generated EPUBs, or conversion outputs.

Suggested manual pass:

1. Upload each generated PDF through the app.
2. Download the EPUB.
3. Save outputs under ignored `testsets/epubs/`.
4. Run EPUBCheck on each EPUB.
5. Open representative outputs in KOReader and Kobo where available.
6. Confirm source PDFs and result EPUBs are deleted from Vercel Blob after use.
