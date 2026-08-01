# Local PDF to EPUB

A private local web app for converting PDFs into EPUB files. The app runs on
your machine with FastAPI, stores jobs in SQLite, keeps files under `data/`, and
uses Baidu PaddleOCR only for hosted document parsing.

The previous Vercel/Blob implementation remains in git history and in the
legacy Next.js source tree, but the supported path in this branch is local-first.

## What It Does

- PIN-protected local `/login` and `/convert` pages
- Upload creates a SQLite job immediately, so reloads and closed tabs can see
  running jobs again
- Background worker continues conversions outside the browser request
- Local file storage for uploads, raw OCR JSON, page images, EPUBs, and logs
- Baidu PaddleOCR-VL-1.6 document parsing through the official TypeScript SDK
- EPUB builder that preserves OCR Markdown, sanitized raw HTML tables/figures,
  Paddle image assets, and rendered PNG formula images
- The first PDF page is used as the EPUB cover image; full PDF-page chapters are
  only used as a fallback when OCR fails
- Download, cancel, retry, and delete controls for each saved job
- Visual fallback EPUB when Paddle parsing fails but local page rendering works
- Optional `.kepub.epub` copy for Kobo stock-reader testing

## Privacy

The source PDF is saved locally. The only external conversion call is the Baidu
PaddleOCR document parsing request. Generated files remain under `data/` until
you delete the job.

## Requirements

- Python 3.11 or newer
- Node.js 22 or newer
- npm
- Poppler (`pdfinfo` and `pdftoppm`)
- Baidu AI Studio / PaddleOCR access token
- Java only for EPUBCheck validation

The PaddleOCR docs say the official TypeScript SDK accepts local `filePath`
inputs and calls the hosted PaddleOCR API; the PaddleOCR-VL docs describe the
layout, formula, table, chart, and document parsing pipeline:

- https://www.paddleocr.ai/latest/en/version3.x/inference_deployment/serving/paddleocr_official_api/typescript.html
- https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html

## Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
npm install
python scripts/generate-local-secrets.py "1234"
```

Create `.env` from `.env.example`, then fill in:

```sh
APP_PIN_HASH=
SESSION_SECRET=
PADDLEOCR_ACCESS_TOKEN=
```

Run the app:

```sh
. .venv/bin/activate
npm run local:run
```

Open `http://127.0.0.1:8000/login`.

## Change The PIN Hash

Generate a new hash:

```sh
. .venv/bin/activate
python scripts/generate-local-secrets.py "4321"
```

Update `APP_PIN_HASH` in `.env`, restart the FastAPI server, and sign in with
the new PIN.

The local generator allows short PINs because this app is meant for private use
on your own machine. Keep `SESSION_SECRET` random and do not expose the server
on a public network with a short PIN.

## Jobs And Reloads

Jobs are stored in `data/app.db`. Uploading a PDF creates a job row before OCR
starts, so the Saved jobs table shows queued and running work after a page
reload. If the FastAPI server itself restarts, queued/running jobs are recovered
and put back on the local worker queue.

Job files live here:

```text
data/
  app.db
  uploads/<job_id>/source.pdf
  ocr/<job_id>/raw-result.json
  ocr/<job_id>/assets/
  pages/<job_id>/page-*.png
  epubs/<job_id>/<title>.epub
  logs/<job_id>.log
```

Use Delete in the app to remove a job and its local files.

## Math And Kobo

The default math strategy is PNG-first:

- Baidu/Paddle TeX snippets such as `$N = 6$` are rendered locally with MathJax
  and Sharp.
- The rendered PNG is embedded inline or as a display equation.
- The original TeX is preserved in the image `alt` text.
- The `.kepub.epub` checkbox creates a second file with Kobo's sideload
  extension so you can test Kobo's stock renderer on the Clara Colour.

Kobo's public EPUB spec says MathML is supported on Kobo eInk readers and that
using `.kepub.epub` invokes Kobo's WebKit-based reader path. KOReader is still
best treated as uneven for MathML, so the converter does not depend on MathML
rendering for readability.

## Limits

The local app does not inherit Vercel request, response, function, or Blob
timeouts. Defaults are aligned to PaddleOCR async document parsing constraints:

- `MAX_PDF_SIZE_MB=200`
- `MAX_PDF_PAGES=1000`
- `MAX_IMAGE_SIZE_MB=256`
- `MAX_TOTAL_ASSET_MB=1024`

For a 100-page PDF, conversion time depends mostly on Baidu queue time and local
page-image rendering. The browser can be closed while the local worker keeps
running.

## Test Set

The manifest includes small research papers, HTML-to-PDF articles, scanned-like
fixtures, and a real large math-heavy book:

- Mathematics for Machine Learning official PDF:
  https://mml-book.github.io/book/mml-book.pdf

Download fixtures:

```sh
npm run prepare-testset
```

Large local smoke test without spending Baidu quota:

```sh
. .venv/bin/activate
python scripts/smoke-local.py \
  --pdf testsets/pdfs/mathematics-for-machine-learning.pdf \
  --mode fixture \
  --fresh \
  --epubcheck
```

Small live Baidu smoke test:

```sh
. .venv/bin/activate
python scripts/smoke-local.py \
  --pdf testsets/pdfs/attention-all-you-need.pdf \
  --mode live \
  --allow-small \
  --kepub \
  --epubcheck
```

## Development

```sh
. .venv/bin/activate
pytest
npm run lint
npm run typecheck
npm test
```

Do not commit `.env`, `data/`, downloaded PDFs, generated EPUBs, or temp files.
