# Local PDF to EPUB

A private local web app for converting PDFs into EPUB files. The app runs on
your machine with FastAPI, stores jobs in SQLite, keeps files under `data/`, and
uses Baidu PaddleOCR only for hosted document parsing.

The previous Vercel/Blob implementation is preserved on the
`legacy-vercel-nextjs` branch. The supported app on `main` is local-first.

## What It Does

- PIN-protected local `/login` and `/convert` pages
- Upload creates a SQLite job immediately, so reloads and closed tabs can see
  running jobs again
- Background worker continues conversions outside the browser request
- Local file storage for uploads, raw OCR JSON, page images, EPUBs, and logs
- Baidu document parsing through the official TypeScript SDK, with selectable
  `PaddleOCR-VL-1.6`, `PaddleOCR-VL-1.5`, `PaddleOCR-VL`, and `PP-StructureV3`
  models
- Automatic OCR retry path: full-PDF submit first, then parallel PDF chunks
  OCR if Baidu does not accept the PDF upload promptly
- EPUB builder that preserves OCR Markdown, sanitized raw HTML tables/figures,
  Paddle image assets, PNG formula images for plain EPUB, and MathML formulas
  for Kobo KEPUB
- The first PDF page is used as the EPUB cover image; PDF page screenshots are
  not used as EPUB content
- Comic/manga mode that bypasses Baidu, renders PDF pages locally, and wraps
  Kindle Comic Converter for Kobo Clara Colour KEPUB, plain EPUB, or CBZ output
- Download, cancel, retry, and delete controls for each saved job
- Optional Kobo MathML `.kepub.epub` output for Kobo stock-reader testing

## Privacy

The source PDF is saved locally. Document/paper jobs call Baidu PaddleOCR for
hosted parsing. Comic/manga jobs are local-only after upload: the app renders
pages on your machine and runs KCC locally. Generated files remain under `data/`
until you delete the job.

## Requirements

- Python 3.11 or newer
- Node.js 22 or newer
- npm
- Poppler (`pdfinfo` and `pdftoppm`)
- Baidu AI Studio API key
- Optional Gemini API key for failed-equation repair
- Optional for comic/manga mode: Kindle Comic Converter `kcc-c2e` or a local KCC
  source checkout
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

Create `.env` from `.env.example`, then fill in the secrets. For normal
private use, `.env` can contain only `APP_PIN_HASH`, `SESSION_SECRET`, and
`BAIDU_AI_STUDIO_API_KEY`; every other setting below has the shown default.

```sh
APP_PIN_HASH=
SESSION_SECRET=
BAIDU_AI_STUDIO_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
BAIDU_AI_STUDIO_BASE_URL=https://aistudio.baidu.com/llm/lmapi/v3
BAIDU_AI_STUDIO_MODEL=ernie-4.5-turbo-128k
LOCAL_DATA_DIR=data
LOCAL_HOST=127.0.0.1
LOCAL_PORT=8000
LOCAL_PADDLE_MODE=live
LOCAL_PADDLE_MODEL=PaddleOCR-VL-1.6
LOCAL_INCLUDE_PAGE_SNAPSHOTS=true
LOCAL_PADDLE_SUBMIT_TIMEOUT_SECONDS=180
LOCAL_PADDLE_AUTO_OCR_TIMEOUT_SECONDS=300
LOCAL_PADDLE_STATUS_TIMEOUT_SECONDS=30
LOCAL_PADDLE_CHUNK_PAGES=2
LOCAL_PADDLE_CHUNK_TARGET_MB=1
LOCAL_PADDLE_CHUNK_CONCURRENCY=12
LOCAL_PADDLE_CHUNK_TIMEOUT_SECONDS=180
LOCAL_PADDLE_CHUNK_RETRIES=1
LOCAL_PADDLE_CHUNK_RETRY_RASTER_DPI=160
LOCAL_PADDLE_AUTO_CHUNK_MIN_PAGES=20
LOCAL_PADDLE_AUTO_CHUNK_MIN_BYTES_PER_PAGE=350000
LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS=120
LOCAL_PADDLE_PAGE_SUBMIT_RETRIES=2
LOCAL_PADDLE_POLL_SECONDS=5
LOCAL_WORKER_POLL_SECONDS=1
LOCAL_CREATE_KEPUB_DEFAULT=false
LOCAL_SNAPSHOT_DPI=120
LOCAL_FIGURE_CROP_DPI=240
LOCAL_MATH_REPAIR_PROVIDER=off
LOCAL_LLM_REQUEST_TIMEOUT_SECONDS=60
LOCAL_LLM_MAX_FAILED_FORMULAS_PER_JOB=200
LOCAL_KCC_SOURCE_DIR=tmp/kcc-source-work
```

`BAIDU_AI_STUDIO_API_KEY` is the default credential name for both Baidu
PaddleOCR document parsing and Baidu AI Studio LLM fallback. Older local `.env`
files that still contain `PADDLEOCR_ACCESS_TOKEN` continue to work as a legacy
fallback, but new setup should use the AI Studio name.

For comic/manga conversion, install or clone KCC:

```sh
git clone https://github.com/ciromattia/kcc.git tmp/kcc-source-work
```

The app uses `LOCAL_KCC_PROFILE=KoCC` by default for Kobo Clara Colour. If you
install a standalone CLI instead, set `LOCAL_KCC_C2E_COMMAND=kcc-c2e`.
`LOCAL_KCC_DISABLE_ROTATE=true` keeps KCC from rotating wide panels by default,
which is more consistent for PDF-to-webtoon conversions.

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

During Baidu submission, progress can only include a remote `paddle_job_id`
after Baidu accepts the upload. To avoid jobs looking frozen at `0/N`, the app
now shows the specific stage: full-PDF submit, rendered-page submit, or remote
page OCR. In Auto retry mode, image-heavy PDFs go straight to PDF chunks, and
full-PDF timeouts switch to PDF chunks instead of the slower rendered-page OCR
path. `Rendered pages` is still available as an explicit OCR path for files
where Baidu cannot parse PDF input at all. If OCR still fails after retries, the
worker retries the failed chunk as smaller page-level PDF submissions. If those
page resubmits also fail, the job fails clearly instead of inserting local
fallback text; use the original PDF in Kobo, KOReader, or another PDF reader
when you want visual page fidelity.

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

## Parser Controls

The upload form starts with `Conversion type`:

- `Document / paper`: sends the PDF through Baidu OCR and builds a reflowable
  EPUB.
- `Comic / manga`: bypasses Baidu, renders the PDF pages locally, and sends the
  rendered images to KCC.

Document jobs have two parser controls:

- `Baidu model`: use `PaddleOCR-VL-1.6` by default. Try `PaddleOCR-VL-1.5`,
  `PaddleOCR-VL`, or `PP-StructureV3` when a document mostly converts well but a
  specific equation/table/figure is wrong.
- `OCR path`: keep `Auto retry` for normal use. `Full PDF only` is useful when
  you want to test Baidu's direct PDF parser. `PDF chunks` splits the source PDF
  into small batches and submits them in parallel, which is the preferred
  fallback for image-heavy papers. `Rendered pages` skips full-PDF upload and
  sends locally rendered page images one by one; use it only when Baidu cannot
  parse the PDF itself.
- `Math repair`: `Off`, `Gemini`, `Baidu AI Studio`, or either fallback chain.
  The selected provider is called only for formulas that fail local MathJax
  conversion. Plain EPUB repairs target PNG rendering; Kobo KEPUB repairs target
  MathML conversion.

Comic jobs have two KCC controls:

- `Output`: Kobo KEPUB, plain EPUB, or CBZ.
- `Layout`: manga right-to-left, comic left-to-right, or webtoon/long strip.
  The default is Kobo KEPUB + webtoon/long strip because that gave the best
  result for tall PDF chapters on Kobo Clara Colour.

## Math And Kobo

The document converter now uses two math strategies:

- Plain `.epub`: Baidu/Paddle TeX snippets such as `$N = 6$` are rendered
  locally with MathJax and Sharp, then embedded as PNG images.
- Kobo `.kepub.epub`: formulas are converted from TeX to native MathML and the
  XHTML manifest entries are marked with `properties="mathml"`.
- Local syntax guessing is disabled. The first render pass uses the OCR formula
  exactly as returned.
- If a formula does not compile or convert to MathML and `Math repair` is
  enabled, all failed formulas for that job are sent together in one strict JSON
  request to Gemini, Baidu AI Studio, or the selected fallback chain.
- AI repair candidates must pass MathJax before they are embedded.
- Plain EPUB preserves the original TeX in image `alt` text.
- If a formula still cannot render, the EPUB keeps the original TeX visibly as
  source text instead of dropping it or emitting broken markup.
- The `Create Kobo MathML .kepub.epub` checkbox builds a second file; it is not
  a byte-for-byte copy of the PNG EPUB.

Useful math-repair env defaults:

```sh
LOCAL_MATH_REPAIR_PROVIDER=off
LOCAL_LLM_REQUEST_TIMEOUT_SECONDS=60
LOCAL_LLM_MAX_FAILED_FORMULAS_PER_JOB=200
```

Set `LOCAL_MATH_REPAIR_PROVIDER=gemini_baidu` if you want the upload form to
default to Gemini first and Baidu AI Studio fallback.

Kobo's public EPUB spec says MathML is supported on Kobo eInk readers and that
using `.kepub.epub` invokes Kobo's WebKit-based reader path. For KOReader or
non-Kobo readers, prefer the plain EPUB with PNG math unless you specifically
want to test MathML.

## Limits

The local app does not inherit hosted request, response, function, or object
storage timeouts. Defaults are aligned to PaddleOCR async document parsing
constraints:

- `MAX_PDF_SIZE_MB=200`
- `MAX_PDF_PAGES=1000`
- `MAX_IMAGE_SIZE_MB=256`
- `MAX_TOTAL_ASSET_MB=1024`

For a 100-page PDF, conversion time depends mostly on Baidu queue time and, when
needed, local page-image rendering for OCR input. The browser can be closed
while the local worker keeps running.

OCR timeout controls:

- `LOCAL_PADDLE_SUBMIT_TIMEOUT_SECONDS`: how long to wait for Baidu to accept a
  full-PDF upload before Auto retry can switch away from it. Default: 180
  seconds.
- `LOCAL_PADDLE_AUTO_OCR_TIMEOUT_SECONDS`: total OCR budget for the Auto path
  before the worker fails the job instead of drifting into a long retry loop.
  Default: 300 seconds.
- `LOCAL_PADDLE_CHUNK_PAGES`: how many PDF pages to put in each fallback chunk.
  Default: 2.
- `LOCAL_PADDLE_CHUNK_TARGET_MB`: approximate target size for PDF chunks. The
  chunker starts a new chunk before this size when possible, while never
  splitting a single source page. Default: 1 MB.
- `LOCAL_PADDLE_CHUNK_CONCURRENCY`: how many PDF chunks to submit to Baidu at
  once. Default: 12.
- `LOCAL_PADDLE_CHUNK_TIMEOUT_SECONDS`: per-chunk Baidu polling budget. Default:
  180 seconds.
- `LOCAL_PADDLE_CHUNK_RETRIES`: how many retry rounds to run for failed PDF
  chunks. Multi-page chunks are split into single-page PDFs before retrying.
  Default: 1.
- `LOCAL_PADDLE_CHUNK_RETRY_RASTER_DPI`: when a failed retry page is still
  larger than `LOCAL_PADDLE_CHUNK_TARGET_MB`, resubmit a lightweight rasterized
  one-page PDF to Baidu. Set to `0` to disable. Default: 160 DPI.
- `LOCAL_FIGURE_CROP_DPI`: resolution used when rendering source pages for
  preserved figure crops. Default: 240 DPI.
- `LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS`: how long each rendered page upload
  can take.
- `LOCAL_PADDLE_PAGE_SUBMIT_RETRIES`: rendered-page upload attempts per page.

The slowest path is rendered-page OCR, because it creates one Baidu job per page.
Auto avoids that path by default. For large, image-heavy PDFs, Auto skips the
full-PDF wait and submits small parallel PDF chunks. The default chunk size is
two pages so a slow chart-heavy page does not trap a larger page range until the
end of the job. For smaller PDFs, Auto tries the full PDF first, but stops
within the configured Auto budget and then uses PDF chunks if time remains. Use
`OCR path: Rendered pages` only as a manual escape hatch for PDFs that Baidu
cannot parse as PDF chunks. If an individual PDF chunk times out, it is
resubmitted once as single-page PDF input; if the retry page is unusually large,
the app rasterizes that page into a smaller one-page PDF before resubmitting it
to Baidu. If the resubmitted page still fails, the job fails clearly.

## Test Set

The manifest lists small research papers, HTML-to-PDF article candidates,
scanned-like fixture ideas, and a real large math-heavy book:

- Mathematics for Machine Learning official PDF:
  https://mml-book.github.io/book/mml-book.pdf

The repository does not commit downloaded PDFs. Put real test PDFs under
`testsets/pdfs/` or point the smoke script at any local PDF:

```sh
mkdir -p testsets/pdfs
curl -L https://arxiv.org/pdf/1706.03762 -o testsets/pdfs/attention-all-you-need.pdf
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
  --math-repair gemini_baidu \
  --kepub \
  --epubcheck
```

## Development

```sh
. .venv/bin/activate
pytest
npm run node:check
node local_app/node/math_render.mjs < tests/fixtures/math-render-smoke.json
```

Do not commit `.env`, `data/`, downloaded PDFs, generated EPUBs, or temp files.
