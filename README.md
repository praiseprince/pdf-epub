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
- Automatic OCR retry path: full-PDF submit first, then rendered page-by-page
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

Create `.env` from `.env.example`, then fill in:

```sh
APP_PIN_HASH=
SESSION_SECRET=
BAIDU_AI_STUDIO_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
BAIDU_AI_STUDIO_MODEL=ernie-4.5-turbo-128k
LOCAL_PADDLE_MODEL=PaddleOCR-VL-1.6
LOCAL_PADDLE_SUBMIT_TIMEOUT_SECONDS=120
LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS=120
LOCAL_PADDLE_PAGE_SUBMIT_RETRIES=2
LOCAL_MATH_REPAIR_PROVIDER=off
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
page OCR. In Auto retry mode, a full-PDF submit timeout switches to rendered
page-by-page OCR. If OCR still fails after retries, the job fails clearly; use
the original PDF in Kobo, KOReader, or another PDF reader when you want visual
page fidelity.

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
  you want to test Baidu's direct PDF parser. `Rendered pages` skips full-PDF
  upload and sends locally rendered page images one by one.
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
  full-PDF upload before Auto retry switches to rendered pages.
- `LOCAL_PADDLE_PAGE_SUBMIT_TIMEOUT_SECONDS`: how long each rendered page upload
  can take.
- `LOCAL_PADDLE_PAGE_SUBMIT_RETRIES`: rendered-page upload attempts per page.

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
