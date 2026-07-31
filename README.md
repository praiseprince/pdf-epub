# Private PDF to EPUB

A minimal, private, stateless PDF-to-EPUB web app for one person.

The app lets you sign in with a personal PIN, upload a PDF directly to private
Vercel Blob storage, send a short-lived signed PDF URL to Baidu PaddleOCR for
document parsing, and download a generated EPUB 3 file. It intentionally keeps
no accounts, database, conversion history, analytics, billing, document library,
or persistent backend worker.

## Privacy Notice

The source PDF is processed by Baidu's hosted PaddleOCR service. The app shows
this notice before upload:

> The PDF is temporarily sent to Baidu PaddleOCR for document parsing.

Temporary files are stored under the private Blob `tmp/` namespace and are
deleted after conversion, after download cleanup, by the Delete now button, or
by scheduled cleanup. No conversion history is intentionally retained.

## Features

- PIN-protected `/login` and `/convert` pages
- Direct browser upload to private Vercel Blob, avoiding Function body limits
- Asynchronous PaddleOCR-VL-1.6 document parsing through the official
  `@paddleocr/api-sdk`
- Stateless signed job tokens, no database
- Markdown AST normalization before EPUB generation
- EPUB 3 output with text, headings, links, lists, footnotes, tables, figures,
  captions, internal images, and MathJax SVG formula rendering
- Signed private Blob download URLs
- Delete-now, cancellation cleanup, stale-file cleanup, and daily cron cleanup
- EPUBCheck validation in CI

## Requirements

- Node.js 22 or newer
- npm
- A Vercel project
- Vercel Blob enabled for that project
- A PaddleOCR AI Studio access token
- Java only when running EPUBCheck locally

## PaddleOCR Access Token

Create or sign in to Baidu AI Studio, enable PaddleOCR document parsing access,
and create an access token for the hosted API. Set it as:

```sh
PADDLEOCR_ACCESS_TOKEN=...
```

The app uses `PaddleOCRClient`, `Model.PaddleOCRVL16`, and the asynchronous
document parsing methods from the official TypeScript SDK. PaddleOCR has
advertised a free document-parsing quota, but that quota may change and should
not be treated as guaranteed capacity.

Official references:

- PaddleOCR TypeScript SDK package: https://www.npmjs.com/package/@paddleocr/api-sdk
- PaddleOCR documentation: https://www.paddleocr.ai/

## Environment

Copy `.env.example` to `.env.local` for local development, or set the same
variables in Vercel:

```sh
APP_PIN_HASH=
SESSION_SECRET=
JOB_TOKEN_SECRET=
PADDLEOCR_ACCESS_TOKEN=
BLOB_READ_WRITE_TOKEN=
CRON_SECRET=

MAX_PDF_SIZE_MB=50
MAX_PDF_PAGES=100
JOB_EXPIRATION_MINUTES=60
MAX_IMAGE_SIZE_MB=20
MAX_TOTAL_ASSET_MB=300
```

Generate the PIN hash and secrets:

```sh
npm run generate-secrets -- "your-long-personal-pin"
```

Use a long numeric or alphanumeric passcode, at least eight characters. Store
the generated values once and do not commit `.env.local`.

## Vercel Blob

In Vercel, enable Blob storage for the project and add the generated
`BLOB_READ_WRITE_TOKEN` to the project environment variables. The app uses:

- private Blob objects
- client uploads
- server-issued signed GET URLs
- short-lived `tmp/<job-uuid>/...` pathnames

Vercel Hobby limits and allowances can change. The implementation is designed
around current documented limits for direct Blob upload/download, private Blob,
signed URLs, 4.5 MB Function request/response bodies, and 300 second Hobby
Functions.

Official references:

- Vercel Function limits: https://vercel.com/docs/functions/limitations
- Vercel Blob client uploads: https://vercel.com/docs/vercel-blob/client-upload
- Vercel Blob private storage: https://vercel.com/docs/vercel-blob/private-storage
- Vercel Blob signed URLs: https://vercel.com/docs/vercel-blob/using-blob-sdk#generating-signed-urls
- Vercel Blob usage and pricing: https://vercel.com/docs/vercel-blob/usage-and-pricing

## Install

```sh
npm install
```

## Run Locally

```sh
npm run dev
```

Open `http://localhost:3000/login`, enter the PIN, then go through:

PIN -> Upload PDF -> Convert -> Download EPUB -> Delete

Local conversion requires valid Vercel Blob and PaddleOCR credentials. Unit
tests and sample EPUB generation do not send files to PaddleOCR.

## Deploy To Vercel Hobby

1. Push this repository to GitHub.
2. Import the project in Vercel.
3. Add the environment variables listed above.
4. Enable Vercel Blob for the project.
5. Deploy.

The included `vercel.json` sets Node.js Function duration limits and one daily
cleanup cron for `/api/cleanup`. The cron route requires the `x-cron-secret`
header to match `CRON_SECRET`; if you call it manually, send that header.

## Temporary Deletion

Temporary Blob paths are restricted to:

```text
tmp/<job-uuid>/source.pdf
tmp/<job-uuid>/assets/...
tmp/<job-uuid>/result.epub
```

Deletion behavior:

- source PDFs and OCR resources are deleted after successful EPUB generation
- generated EPUBs expire after `JOB_EXPIRATION_MINUTES`, default 60
- Delete now removes the whole active job namespace
- cancellation aborts client-side work where possible and deletes known temp files
- `/api/cleanup` deletes expired objects only under valid app `tmp/` paths
- `npm run delete-temp-blobs` deletes all valid app temp objects from the
  configured Blob store

To uninstall the app completely, run `npm run delete-temp-blobs` with
`BLOB_READ_WRITE_TOKEN` available, then remove the Vercel project, Blob store,
and environment variables.

## Current Limits

Defaults are configurable:

- `MAX_PDF_SIZE_MB=50`
- `MAX_PDF_PAGES=100`
- `JOB_EXPIRATION_MINUTES=60`
- `MAX_IMAGE_SIZE_MB=20`
- `MAX_TOTAL_ASSET_MB=300`

These are conservative personal-use limits intended to keep finalization inside
Vercel Hobby Function duration and Blob usage limits.

## Test

Run the local checks:

```sh
npm run lint
npm run typecheck
npm test
npm run sample-epub -- tmp/sample.epub
npm run build
npm audit --audit-level=high
```

Run EPUBCheck locally if Java and the EPUBCheck jar are installed:

```sh
EPUBCHECK_JAR=/path/to/epubcheck.jar npm run epubcheck -- tmp/sample.epub
```

CI downloads EPUBCheck v5.3.0, generates `tmp/sample.epub`, validates it, and
then builds the Next.js app.

EPUBCheck releases: https://github.com/w3c/epubcheck/releases

## Common Errors

PaddleOCR authentication failed.
: Check `PADDLEOCR_ACCESS_TOKEN`, confirm the token is active, and redeploy
  after changing Vercel environment variables.

PaddleOCR free quota appears to be exhausted.
: Wait for quota reset or review the current AI Studio limits. The advertised
  free quota may change.

Document parsing failed.
: The hosted service rejected or failed the document. Try a smaller PDF or a
  non-damaged source file.

Upload failed.
: Check `BLOB_READ_WRITE_TOKEN`, Blob store status, file size, and whether the
  file is really a PDF.

The conversion expired.
: The signed upload or job token expired. Start a new conversion.

The temporary file has already been deleted.
: Cleanup already ran, Delete now was pressed, or the Blob path no longer
  exists.

## Upstream Attribution

This implementation is inspired by
https://github.com/jarodise/pdf2epub-paddle. That project is MIT licensed. The
required upstream license and attribution are preserved in `LICENSE` and
`NOTICE`; keep both files in redistributed copies.
