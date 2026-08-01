# Private PDF to EPUB

A minimal, private, stateless PDF-to-EPUB web app for one person.

The app lets you sign in with a personal PIN, upload a PDF directly to private
Vercel Blob storage, send a short-lived signed PDF URL to Baidu PaddleOCR for
document parsing, and download a generated EPUB 3 file. It intentionally keeps
no accounts, database, backend conversion history, analytics, billing, document
library, or persistent backend worker.

## Privacy Notice

The source PDF is processed by Baidu's hosted PaddleOCR service. The app shows
this notice before upload:

> The PDF is temporarily sent to Baidu PaddleOCR for document parsing.

Temporary files are stored under the private Blob `tmp/` namespace and are
deleted after conversion, after download cleanup, by the Delete now button, or
by scheduled cleanup. No backend conversion history is retained. The convert
page stores short-lived signed job tokens in this browser so a submitted job can
be checked again after a reload or browser restart.

## Features

- PIN-protected `/login` and `/convert` pages
- Direct browser upload to private Vercel Blob, avoiding Function body limits
- Asynchronous PaddleOCR-VL-1.6 document parsing through the official
  `@paddleocr/api-sdk`
- Stateless signed job tokens, no database
- Browser-only saved jobs panel for reload/restart recovery
- Blob-backed chunked EPUB finalization to avoid one large timeout-prone build
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

MAX_PDF_SIZE_MB=1024
MAX_PDF_PAGES=1000
JOB_EXPIRATION_MINUTES=60
MAX_IMAGE_SIZE_MB=256
MAX_TOTAL_ASSET_MB=1024
PDF_INSPECTION_MAX_MB=256
FINALIZE_IMAGE_PAGE_BATCH=5
FINALIZE_CHAPTER_BATCH=5
```

The checked-in defaults are finite guardrails chosen for a personal Vercel
Hobby deployment. For `MAX_PDF_SIZE_MB`, `MAX_PDF_PAGES`,
`MAX_IMAGE_SIZE_MB`, `MAX_TOTAL_ASSET_MB`, and `PDF_INSPECTION_MAX_MB`, you can
still set `0`, `none`, `off`, or `unlimited` to disable that app-level cap. This
does not remove upstream limits from the browser, Vercel Blob, Vercel
Functions, PaddleOCR, available memory, or your PaddleOCR quota.

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

## Manage Vercel Secrets

Production conversion requires `PADDLEOCR_ACCESS_TOKEN` in Vercel. Add or rotate
it without printing the token in source control:

```sh
vercel env rm PADDLEOCR_ACCESS_TOKEN production
vercel env rm PADDLEOCR_ACCESS_TOKEN preview

vercel env add PADDLEOCR_ACCESS_TOKEN production
vercel env add PADDLEOCR_ACCESS_TOKEN preview
```

Paste the Baidu AI Studio / PaddleOCR token when prompted, then redeploy:

```sh
vercel deploy --prod --yes
```

To change the app PIN, generate a new hash locally:

```sh
npm run generate-secrets -- "your-new-long-pin"
```

Copy only the generated `APP_PIN_HASH=...` value and update Vercel:

```sh
vercel env rm APP_PIN_HASH production
vercel env rm APP_PIN_HASH preview

vercel env add APP_PIN_HASH production
vercel env add APP_PIN_HASH preview
```

Paste the new hash when prompted, then redeploy:

```sh
vercel deploy --prod --yes
```

Existing browser sessions can remain valid until their cookie expires. To force
a fresh login everywhere, rotate `SESSION_SECRET` the same way and redeploy.
Rotate `JOB_TOKEN_SECRET` to invalidate active in-progress conversions.

## Temporary Deletion

Temporary Blob paths are restricted to:

```text
tmp/<job-uuid>/source.pdf
tmp/<job-uuid>/finalize-state.json
tmp/<job-uuid>/text/...
tmp/<job-uuid>/assets/...
tmp/<job-uuid>/result.epub
```

Deletion behavior:

- source PDFs and OCR resources are deleted after successful EPUB generation
- generated EPUBs expire after `JOB_EXPIRATION_MINUTES`, default 60
- browser-saved jobs are pruned when their signed job token expires
- Delete now removes the whole active job namespace
- cancellation aborts client-side work where possible and deletes known temp files
- `/api/cleanup` deletes expired objects only under valid app `tmp/` paths
- `npm run delete-temp-blobs` deletes all valid app temp objects from the
  configured Blob store

To uninstall the app completely, run `npm run delete-temp-blobs` with
`BLOB_READ_WRITE_TOKEN` available, then remove the Vercel project, Blob store,
and environment variables.

## Current Limits

Defaults are configurable. The checked-in example keeps app-level limits aligned
with the main upstream constraints:

- `MAX_PDF_SIZE_MB=1024`
- `MAX_PDF_PAGES=1000`
- `JOB_EXPIRATION_MINUTES=60`
- `MAX_IMAGE_SIZE_MB=256`
- `MAX_TOTAL_ASSET_MB=1024`
- `PDF_INSPECTION_MAX_MB=256`
- `FINALIZE_IMAGE_PAGE_BATCH=5`
- `FINALIZE_CHAPTER_BATCH=5`

Why these numbers:

- `MAX_PDF_SIZE_MB=1024` stays inside the Vercel Hobby Blob storage allowance
  for a personal deployment, even though Blob itself supports much larger
  objects.
- `MAX_PDF_PAGES=1000` matches PaddleOCR's async PDF page limit per request.
- `MAX_IMAGE_SIZE_MB=256` leaves headroom under Vercel Function memory while
  image assets are downloaded, decoded, normalized, and staged.
- `MAX_TOTAL_ASSET_MB=1024` keeps staged conversion assets inside the same
  personal Blob storage envelope.
- `PDF_INSPECTION_MAX_MB=256` avoids buffering very large PDFs in a Function
  just to count pages. Larger PDFs are signature-checked, then PaddleOCR
  enforces its own page/request limits.

Set an app-level limit to `0`, `none`, `off`, or `unlimited` only when you
explicitly want to delegate that constraint to the upstream service.

## Reloads And Long Jobs

After a PDF is submitted to PaddleOCR, the convert page saves the signed job
token in `localStorage`. Use the Saved jobs button on `/convert` to check,
resume, refresh a download link, or delete jobs that are still within
`JOB_EXPIRATION_MINUTES`.

Closing the page during the direct upload cannot resume that upload because no
PaddleOCR job exists yet. After submission, OCR runs asynchronously at
PaddleOCR; the browser only polls status. Final EPUB generation is chunked:
each `/api/jobs/finalize` call prepares a bounded batch of image pages or
chapters, stores staged XHTML/assets in private Blob storage, and returns
progress. The browser keeps calling it until the final call streams the EPUB ZIP
to Blob and returns a download URL.

The Vercel timeout-sensitive parts are now:

- `/api/jobs/submit` is configured for 240 seconds
- `/api/jobs/finalize` is configured for 120 seconds per chunk
- `/api/jobs/status` is short polling and is configured for 30 seconds

For long papers, OCR waiting and EPUB finalization can continue across reloads
as long as the job token has not expired. Extremely large PDFs can still fail if
PaddleOCR rejects them, your quota runs out, Blob storage is exhausted, or the
final packaging step itself becomes too large for a single Function. If that
happens regularly, reduce `FINALIZE_*_BATCH`, split very large PDFs, use Vercel
Workflows, or move packaging to a dedicated worker.

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

Run a local 150-page stress test for the chunked finalizer. This requires
`BLOB_READ_WRITE_TOKEN`, writes `tmp/stress-150-page.pdf` and
`tmp/stress-150-page.epub`, and deletes temporary Blob objects after copying the
EPUB back locally:

```sh
npm run stress-chunked-finalize
```

Prepare a local stress corpus of open-access papers, HTML-printed PDFs, and a
scanned-like image-only PDF:

```sh
npm run prepare-testset
```

The generated PDFs are ignored under `testsets/pdfs/`. See
`testsets/README.md` for the manual conversion pass.

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
