# Local PDF to EPUB

A private FastAPI app for converting PDFs into EPUB/KEPUB files on your own
machine. Document jobs run PaddleOCR locally by default, store progress in
SQLite, and build reflowable EPUBs with MathJax-rendered PNG formulas. Comic
jobs bypass OCR and use Kindle Comic Converter for Kobo/EPUB/CBZ output.

The previous Vercel implementation is preserved on the `legacy-vercel-nextjs`
branch. This branch is local-first.

## Features

- PIN-protected local `/login` and `/convert` pages.
- Saved jobs in `data/app.db`, so reloads and closed tabs can see queued or
  running work again.
- Local PaddleOCR-VL 1.6 document parsing by default.
- Page-by-page local OCR checkpoints for long documents.
- EPUB and optional `.kepub.epub` document output using the same PNG formula
  rendering path.
- First PDF page as the EPUB cover; full PDF page screenshots are not inserted
  as regular reading content.
- Figure/plot preservation by cropping detected visual regions from the source
  PDF.
- Comic/manga mode using KCC with Kobo KEPUB, plain EPUB, or CBZ output.
- Download, cancel, retry, and delete controls for saved jobs.
- Runtime controls for MLX vs CPU OCR and temporary Cloudflare tunnels.

No Gemini, Baidu LLM, or other formula-repair LLM is used. OCR-provided LaTeX is
validated by MathJax; if it renders, the app embeds a PNG formula image. If it
does not render, the original TeX is kept visibly as source text.

## Privacy

In normal `LOCAL_PADDLE_MODE=local` use, document OCR runs on your computer.
Generated uploads, OCR JSON, page images, EPUBs, and logs stay under `data/`.
Comic jobs are also local-only after upload.

`BAIDU_AI_STUDIO_API_KEY` is only needed if you explicitly switch
`LOCAL_PADDLE_MODE=live` for cloud OCR fallback/debugging.

Cloudflare quick tunnels are optional. When enabled, `cloudflared` proxies the
PIN-protected local app to a temporary `trycloudflare.com` URL until you stop
the tunnel or quit the app.

## Requirements

- Python 3.11 or newer for the app.
- Python 3.9-3.13 for the isolated local PaddleOCR environment.
- Node.js 22 or newer and npm.
- Poppler (`pdfinfo` and `pdftoppm`).
- Java only if you want EPUBCheck validation.
- Optional for phone/tablet access: `cloudflared`.
- Optional for comic/manga mode: Kindle Comic Converter `kcc-c2e` or a local KCC
  source checkout.

PaddleOCR's docs describe local PaddleOCR-VL usage, Apple Silicon setup, and
first-run model downloads:

- https://github.com/paddlepaddle/paddleocr/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md
- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html

## Setup

Create the app environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
npm install
python scripts/generate-local-secrets.py "1234"
```

Create `.env` from `.env.example`, then fill in at least:

```sh
APP_PIN_HASH=
SESSION_SECRET=
```

For local OCR, create the isolated PaddleOCR environment with a supported Python:

```sh
/opt/homebrew/bin/python3.12 -m venv .venv_paddleocr
.venv_paddleocr/bin/python -m pip install --upgrade pip setuptools wheel
.venv_paddleocr/bin/python -m pip install paddlepaddle==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.venv_paddleocr/bin/python -m pip install -U "paddleocr[doc-parser]"
.venv_paddleocr/bin/python -m pip install "mlx-vlm>=0.3.11"
```

The first local OCR run downloads official model files to your user cache, for
example `/Users/june/.paddlex/official_models/`.

For comic/manga conversion, install or clone KCC:

```sh
git clone https://github.com/ciromattia/kcc.git tmp/kcc-source-work
```

Run the app:

```sh
. .venv/bin/activate
npm run local:app
```

Open `http://127.0.0.1:8000/login`.

On Apple Silicon, `npm run local:app` starts the MLX-VLM service by default.
Use CPU mode when you want the slower fallback:

```sh
npm run local:cpu
```

## Mac App Bundle

Build the Finder app:

```sh
. .venv/bin/activate
npm run local:package
```

This writes:

```text
dist/PDF to EPUB.app
```

Double-click `PDF to EPUB.app` to open Terminal and start the local server.
Press `Ctrl-C` in that Terminal window to stop the app.

The app bundle copies the source, `.venv`, `.venv_paddleocr`, `node_modules`,
and local `.env` files into:

```text
dist/PDF to EPUB.app/Contents/Resources/pdf-epub
```

Generated jobs and outputs are stored outside the bundle, so app rebuilds do not
wipe them:

```text
~/Library/Application Support/PDF to EPUB/data
```

This is one Finder-visible `.app`, but macOS app bundles are directories under
the hood. It is portable on this Mac as long as Homebrew Python, Poppler,
Node-compatible native libraries, `cloudflared`, and the model caches remain
installed.

The app's Runtime panel lets you switch between MLX and CPU OCR and start/stop a
temporary Cloudflare tunnel. Start the tunnel from the local browser, then open
the displayed URL on your phone or another laptop.

## Environment

Typical private `.env`:

```sh
APP_PIN_HASH=
SESSION_SECRET=
LOCAL_PADDLE_MODE=local
LOCAL_PADDLE_PYTHON=.venv_paddleocr/bin/python
LOCAL_PADDLE_PIPELINE_VERSION=v1.6
LOCAL_PADDLE_DEVICE=cpu
LOCAL_PADDLE_VL_BACKEND=mlx-vlm-server
LOCAL_PADDLE_VL_SERVER_URL=http://127.0.0.1:8111/
LOCAL_START_MLX=true
LOCAL_START_TUNNEL=false
```

Useful defaults documented in `.env.example`:

```sh
LOCAL_DATA_DIR=data
LOCAL_HOST=127.0.0.1
LOCAL_PORT=8000
LOCAL_PADDLE_MODEL=PaddleOCR-VL-1.6
LOCAL_PADDLE_VL_API_MODEL_NAME=PaddlePaddle/PaddleOCR-VL-1.6
LOCAL_PADDLE_VL_MAX_CONCURRENCY=4
LOCAL_OCR_DPI=120
LOCAL_INCLUDE_PAGE_SNAPSHOTS=true
LOCAL_CREATE_KEPUB_DEFAULT=false
LOCAL_SNAPSHOT_DPI=120
LOCAL_FIGURE_CROP_DPI=240
MAX_PDF_SIZE_MB=200
MAX_PDF_PAGES=1000
MAX_IMAGE_SIZE_MB=256
MAX_TOTAL_ASSET_MB=1024
```

Cloud OCR fallback/debug settings:

```sh
LOCAL_PADDLE_MODE=live
BAIDU_AI_STUDIO_API_KEY=
```

## Jobs And Reloads

Uploading a PDF creates a job row before OCR starts. If you reload or close the
browser, the Saved jobs table will still show queued/running work. If the
FastAPI server restarts, queued/running jobs are recovered and put back on the
worker queue.

For local OCR, the worker renders pages locally and writes checkpoint JSON files
under:

```text
data/ocr/<job_id>/local-page-checkpoints/page-0001.json
```

If a long conversion fails mid-document, retrying the job can reuse completed
page checkpoints instead of starting that OCR work from zero.

Job files live here:

```text
data/
  app.db
  uploads/<job_id>/source.pdf
  ocr/<job_id>/raw-result.json
  ocr/<job_id>/assets/
  ocr/<job_id>/local-page-checkpoints/
  pages/<job_id>/page-*.png
  epubs/<job_id>/<title>.epub
  logs/<job_id>.log
```

Use Delete in the app to remove a job and its local files.

## UI Options

Document jobs:

- Choose a PDF.
- Choose `Document / paper`.
- Optional: `Also create Kobo KEPUB`.

Document OCR always uses PaddleOCR-VL 1.6 and the internal auto path.

Runtime controls:

- OCR: MLX or CPU.
- Tunnel: start, stop, and open the temporary Cloudflare URL.

Comic jobs:

- Choose a PDF.
- Choose `Comic / manga`.
- Output: Kobo KEPUB, plain EPUB, or CBZ.
- Layout: manga right-to-left, comic left-to-right, or webtoon/long strip.

Comic mode does not use OCR or formula rendering.

## Math And Kobo

Both document `.epub` and `.kepub.epub` use the same formula path:

```text
OCR LaTeX -> MathJax validation/render -> PNG formula image -> EPUB
```

The original TeX is preserved in image alt text where rendering succeeds. If a
formula fails MathJax validation, the original TeX remains visible as text. The
app no longer generates MathML-specific KEPUB output.

## Testing

The test set manifest lives at `testsets/manifest.json`. Downloaded PDFs and
generated outputs are ignored by git.

Download the direct-PDF corpus entries:

```sh
. .venv/bin/activate
python scripts/download-testset.py
```

The manifest also includes HTML-derived entries. Those are generated locally
from the source pages instead of downloaded directly.

For the large Mathematics for Machine Learning book, use a test-only page cap:

```sh
. .venv/bin/activate
python scripts/smoke-local.py \
  --pdf testsets/pdfs/mathematics-for-machine-learning.pdf \
  --mode local \
  --page-limit 150 \
  --fresh \
  --kepub \
  --epubcheck
```

That `--page-limit` creates a temporary truncated PDF for the smoke run only; it
does not change app limits.

Small document smoke test:

```sh
. .venv/bin/activate
python scripts/smoke-local.py \
  --pdf testsets/pdfs/adam-optimizer.pdf \
  --mode local \
  --allow-small \
  --kepub \
  --epubcheck
```

Comic smoke test:

```sh
. .venv/bin/activate
python scripts/smoke-local.py \
  --pdf testsets/pdfs/pepper-carrot-episode-22-the-voting-system.pdf \
  --conversion-mode comic \
  --comic-output-format kepub \
  --comic-layout webtoon \
  --allow-small \
  --fresh
```

## Development

```sh
. .venv/bin/activate
pytest
npm run node:check
node local_app/node/math_render.mjs < tests/fixtures/math-render-smoke.json
```

Do not commit `.env`, virtualenvs, `data/`, downloaded PDFs, generated EPUBs, or
temp files.
