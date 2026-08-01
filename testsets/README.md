# Conversion Test Set

This directory defines a local corpus for exercising PDF-to-EPUB conversion
quality. The repository commits only the manifest; downloaded PDFs are ignored
under `testsets/pdfs/`.

The corpus intentionally covers:

- two-column research papers
- diagram- and image-heavy papers
- equation-heavy papers
- chart-heavy papers
- online HTML articles printed to PDF
- image-only scanned-like PDFs
- a large real-world 400+ page math-heavy book for timeout and storage testing

The manifest records public source URLs for local testing. Review the source
terms before redistributing downloaded files. Do not commit private PDFs,
generated EPUBs, or conversion outputs.

Suggested manual pass:

1. Upload each generated PDF through the app.
2. Download the EPUB.
3. Save outputs under ignored `testsets/epubs/`.
4. Run EPUBCheck on each EPUB.
5. Open representative outputs in KOReader and Kobo where available.
6. Delete local job files from the app when you no longer need the outputs.
