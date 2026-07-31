Build a minimal, private, stateless PDF-to-EPUB web application.

Use this GitHub repository as the starting point and reference implementation:

https://github.com/jarodise/pdf2epub-paddle

Inspect the repository before coding. Reuse useful logic and ideas, but replace
obsolete PaddleOCR endpoints, weak equation handling, and incorrect image
assumptions with the current official PaddleOCR API.

Preserve all required upstream copyright and license notices.

======================================================================
1. CORE PRODUCT
======================================================================

Create a personal web app with one purpose:

Upload almost any PDF and receive a clean, reflowable EPUB that preserves:

- Text
- Correct reading order
- Headings and sections
- Mathematical formulas
- Figures
- Images
- Captions
- Tables
- Footnotes
- Citations
- Links
- Lists
- Code blocks

The finished EPUB should work well in:

- KOReader
- Kobo's stock EPUB reader where supported
- Other standards-compliant EPUB 3 readers

The app will be deployed publicly on Vercel but protected by a personal access PIN.

This is for one person.

Do not add:

- Accounts
- Registration
- Email
- Password recovery
- Google Drive
- Dropbox
- User profiles
- Billing
- Subscriptions
- Advertisements
- Analytics
- Conversion history
- Document libraries
- Dashboards
- Teams
- Admin panels
- Permanent file storage
- A database
- A locally hosted OCR model
- A persistent backend server

Keep the interface and implementation as small as reasonably possible.

======================================================================
2. USER EXPERIENCE
======================================================================

The complete workflow must be:

1. Visit the application.
2. Enter the access PIN.
3. Select or drag in a PDF.
4. Optionally edit the detected title and author.
5. Press "Convert to EPUB".
6. See simple stage-based progress.
7. Download the EPUB.
8. Delete all temporary files.

Use these progress stages:

- Uploading PDF
- Sending to document parser
- Reading document
- Processing formulas and figures
- Building EPUB
- Ready to download

Do not show fake percentage progress when the upstream API does not provide
real percentage data.

The interface must work well in:

- iPhone Safari
- Desktop Safari
- Chrome
- Firefox
- Edge

Use:

- Large touch-friendly controls
- A clean centered layout
- A clear PDF picker
- Drag-and-drop on desktop
- A cancel button
- A download button
- A delete-now button

Pages:

- /login
- /convert

Do not create a sidebar, dashboard, history screen, settings screen, or document
management interface.

======================================================================
3. ONE SMART CONVERSION MODE
======================================================================

Do not ask whether the PDF is:

- An article
- A research paper
- A book
- A textbook
- A report
- A scanned document

The app should automatically analyze the document.

Initially provide only one conversion mode:

Smart EPUB

Smart EPUB must:

- Reflow ordinary text
- Detect headings and heading hierarchy
- Reconstruct multi-column reading order
- Preserve formulas
- Preserve figures and captions
- Preserve meaningful images
- Preserve tables
- Preserve citations and bibliography entries
- Preserve footnotes
- Generate a table of contents
- Remove repeated headers
- Remove repeated footers
- Remove isolated page numbers
- Join paragraphs split across page boundaries
- Produce valid EPUB 3
- Avoid silently discarding content

Use a hybrid strategy:

- Convert text into reflowable EPUB text.
- Render recognized formulas into EPUB-compatible assets.
- Embed figures and diagrams as images.
- Convert reliable tables to HTML.
- Preserve unreliable formulas, tables, or complex regions as cropped images.

Content preservation is more important than producing perfectly editable text.

Do not add multiple document presets until tests demonstrate that one smart mode
cannot handle the required documents reliably.

An optional advanced checkbox may be added later:

"Prefer visual fidelity for complex content"

When enabled, uncertain formulas, tables, and complex layout regions should be
preserved as images more aggressively.

Do not add this checkbox during the initial implementation unless needed by
tests.

======================================================================
4. DEPLOYMENT TARGET
======================================================================

The finished application must deploy on the Vercel Hobby plan.

Treat current platform limits as constraints, not permanent assumptions.

Before implementing, verify the latest official Vercel documentation for:

- Hobby Function maximum duration
- Function request and response body limits
- Vercel Blob Hobby allowance
- Private Blob support
- Signed Blob URLs
- Client upload API
- Cron availability

At the time this specification was written:

- Vercel Function request and response bodies are limited to 4.5 MB.
- Hobby Functions support up to 300 seconds.
- Vercel Blob supports direct browser uploads.
- Vercel Blob supports private objects and expiring signed URLs.

Do not send PDF binary data through a normal Next.js API route.

Do not return the generated EPUB binary through a normal Function response when
it might exceed the Function response limit.

Use direct Blob upload and signed Blob download URLs.

The application must remain useful within free Hobby allowances for personal
usage of a few PDFs per day.

Do not add paid Vercel services unless absolutely required.

If any required implementation cannot work on the current Hobby plan, stop and
report the exact limitation before adding an external paid service.

======================================================================
5. TECHNOLOGY STACK
======================================================================

Use:

- Next.js
- App Router
- TypeScript
- Strict TypeScript configuration
- Node.js runtime, not Edge runtime, for server routes
- Vercel
- Private Vercel Blob storage
- Official PaddleOCR TypeScript SDK
- A Markdown AST pipeline based on Unified/Remark or an equivalent maintained
  library
- A pure-JavaScript LaTeX renderer
- A JavaScript EPUB 3 builder
- A ZIP library capable of controlling compression and file order
- Sharp or another reliable server-compatible image processor where necessary

Do not use:

- Python in production
- CUDA
- PyTorch
- PaddlePaddle locally
- Poppler in production
- A GPU
- Docker in production
- Pandoc as a system binary
- LibreOffice
- A persistent worker
- Postgres
- SQLite
- Redis
- Supabase
- Firebase
- A long-running server

The existing Python repository is a reference implementation. Port or redesign
the required logic in TypeScript.

======================================================================
6. PADDLEOCR OFFICIAL API
======================================================================

Use the official hosted PaddleOCR API.

Install the official TypeScript SDK:

npm install @paddleocr/api-sdk

Use:

- PaddleOCRClient
- Model.PaddleOCRVL16

The default document-parsing model must be:

PaddleOCR-VL-1.6

The official SDK currently supports document parsing with:

- PaddleOCR-VL-1.6
- PaddleOCR-VL-1.5
- PaddleOCR-VL
- PP-StructureV3

Use PaddleOCR-VL-1.6 by default.

Do not run inference locally.

The SDK should submit the document to Baidu's hosted service.

Use the asynchronous methods rather than keeping a Vercel Function open:

- submitDocumentParsing(...)
- getStatus(jobId)
- waitDocumentParsingResult(job)
- saveDocumentParsingResultResources(...)

The exact installed SDK API and types are the source of truth.

Do not invent unsupported request options.

Use only options accepted by the current PaddleOCRVLOptions TypeScript type.

Enable supported options for:

- Layout detection
- Chart recognition
- Markdown prettification
- Document preprocessing where appropriate
- Page orientation correction where supported
- Page unwarping where supported

PaddleOCR-VL should recognize document elements including:

- Paragraphs
- Headings
- Multi-column layouts
- Formulas
- Tables
- Figures
- Charts
- Images

Use the returned document parsing output, including fields such as:

- jobId
- pages
- markdownText
- markdownImages
- outputImages
- Page index
- Page count
- Structured layout data where exposed
- Reading order where exposed
- Paragraph continuation information where exposed
- Formula content
- Table content
- Figure resources
- Bounding boxes where exposed

Do not assume every field is always present.

Validate the API response using a schema.

The SDK accepts either a file path or file URL. For Vercel, provide a short-lived
signed URL to the temporary private PDF.

Keep the PaddleOCR access token entirely server-side:

PADDLEOCR_ACCESS_TOKEN

Never expose it:

- In browser JavaScript
- In HTML
- In job tokens
- In logs
- In API responses

Use typed PaddleOCR error handling for errors such as:

- Authentication errors
- Invalid requests
- Rate limits
- Service unavailability
- Network failures
- Failed remote jobs
- Request timeouts
- Poll timeouts
- Malformed responses
- Result parsing failures

Implement exponential backoff for retryable errors.

Do not retry:

- Invalid PDFs
- Authentication failures
- Unsupported files
- Quota exhaustion without user action

Show useful human-readable errors.

The PaddleOCR documentation currently advertises up to 20,000 free
document-parsing pages per day.

Do not hardcode that quota.

Do not assume it will remain permanently free.

Handle:

- Quota-exceeded responses
- Account-specific limits
- Changed API limits
- Disabled models
- Renamed models

Add a README section explaining how to obtain an AI Studio access token and set
PADDLEOCR_ACCESS_TOKEN.

Also display a small privacy notice before upload:

"The PDF is temporarily sent to Baidu PaddleOCR for document parsing."

======================================================================
7. ASYNCHRONOUS JOB FLOW
======================================================================

Do not perform the entire conversion inside one HTTP request.

Use this flow:

1. Browser requests a temporary upload authorization.
2. Browser uploads the PDF directly to private Vercel Blob.
3. Server creates a short-lived signed GET URL for that PDF.
4. Server submits the signed URL to PaddleOCR.
5. Server returns a signed application job token.
6. Browser polls the status endpoint every few seconds.
7. Status endpoint calls PaddleOCR getStatus(jobId).
8. When PaddleOCR completes, browser calls the finalize endpoint.
9. Finalize endpoint retrieves the parsed result and assets.
10. Finalize endpoint generates the EPUB.
11. EPUB is written to private Vercel Blob.
12. Server returns a short-lived signed download URL.
13. User downloads the EPUB.
14. App deletes all temporary resources.

Do not hold a Vercel Function open while PaddleOCR processes the document.

A single status request should perform only one non-blocking Paddle status
check.

Suggested polling interval:

- First minute: every 5 seconds
- After one minute: every 10 seconds

Stop polling when:

- Completed
- Failed
- Cancelled
- Expired

Support AbortSignal or an equivalent cancellation path where possible.

======================================================================
8. STATE WITHOUT A DATABASE
======================================================================

Do not use a database.

Do not rely on Vercel Function memory between requests.

Create a cryptographically signed job token containing only minimal metadata:

- Internal job UUID
- PaddleOCR job ID
- Input Blob pathname
- Original filename
- Optional title
- Optional author
- Creation timestamp
- Expiration timestamp

Use a server-side secret:

JOB_TOKEN_SECRET

Sign the token using a maintained cryptographic library such as jose.

Do not include:

- PDF content
- OCR output
- PaddleOCR access token
- PIN
- Blob credentials
- Large data structures

The browser may keep the active job token in session storage.

Do not use local storage for long-term history.

Reject:

- Modified tokens
- Expired tokens
- Tokens with invalid Blob paths
- Tokens referring to another job namespace

Use random UUIDs for Blob paths.

Example temporary paths:

tmp/<job-uuid>/source.pdf
tmp/<job-uuid>/assets/...
tmp/<job-uuid>/result.epub

======================================================================
9. PDF UPLOAD
======================================================================

Use direct client upload to private Vercel Blob.

Do not route PDF bytes through a Vercel Function.

Use the current recommended Vercel Blob client-upload or presigned-PUT flow.

The server must authorize each upload only after verifying the PIN session.

Validate before accepting:

- File extension is .pdf
- MIME type is application/pdf when available
- First bytes match the PDF signature
- File is below the configured size limit
- Filename is sanitized
- Blob pathname cannot be chosen freely by the browser

Initial limits:

MAX_PDF_SIZE_MB=50
MAX_PDF_PAGES=100

The PDF page count may be validated after upload using a lightweight PDF parser.

Reject password-protected or encrypted PDFs with a clear message.

Do not attempt to bypass PDF passwords.

Generate a signed Paddle-readable GET URL valid for approximately one hour.

If signed Blob URLs or their current API differ from this specification, use the
latest official Vercel method.

======================================================================
10. TEMPORARY FILES AND DELETION
======================================================================

No user document should be permanently stored.

Use private Blob storage only as temporary working storage.

Deletion policy:

- Delete the original PDF after EPUB generation succeeds.
- Delete downloaded OCR resources after they are packaged into the EPUB.
- Keep the finished EPUB for no more than one hour.
- Provide a Delete Now button.
- Delete failed and cancelled jobs.
- Delete abandoned temporary files after their expiration time.

Because a browser cannot always reliably confirm that a signed-URL download
finished, do not promise immediate deletion at the exact final byte.

Instead:

1. Start the EPUB download.
2. Offer "Delete now".
3. Automatically request cleanup shortly after the download begins.
4. Retain a maximum one-hour safety expiration.
5. Run stale-file cleanup opportunistically.
6. Add one daily cleanup task if the current Vercel Hobby plan permits it.

The cleanup task must:

- Search only the app's tmp/ namespace.
- Parse timestamps safely.
- Delete files older than the configured expiration.
- Require a secret authorization header.
- Never delete unrelated Blob objects.

If Vercel Cron is not available under the current plan, perform opportunistic
cleanup:

- On login
- Before upload
- During status checks
- After completed downloads

Do not store OCR output or document text in application logs.

======================================================================
11. DOCUMENT NORMALIZATION
======================================================================

Do not pass PaddleOCR Markdown directly into an EPUB without processing it.

Parse Markdown into an AST.

Use structured transformations rather than large regex chains.

Support:

- Headings
- Paragraphs
- Emphasis
- Strong emphasis
- Lists
- Blockquotes
- Links
- Footnotes
- Citations
- Code blocks
- Inline code
- Images
- Captions
- Tables
- Inline math
- Display math

Maintain page-level metadata during normalization.

Reading order:

- Prefer PaddleOCR's returned reading order.
- Respect block ordering information.
- Preserve columns in logical reading order.
- Do not sort solely by horizontal or vertical coordinates when the API already
  provides block order.

Paragraph continuation:

- Use returned page-continuation information when available.
- Join paragraphs across pages only when both pages indicate continuation.
- Preserve paragraph breaks when uncertain.

Hyphenation:

- Repair words split at line or page endings only when evidence is strong.
- Do not remove legitimate hyphens.
- Preserve scientific terms, identifiers, and compound words.

Remove repeated headers and footers only when:

- The same or nearly identical text occurs at a consistent position on several
  pages.
- It is clearly outside the primary content.

Remove standalone page numbers only when they are clearly pagination.

Do not remove:

- Section numbers
- Figure numbers
- Equation numbers
- Years
- Citations
- List numbering
- Bibliography numbering
- Numeric table content

Never silently discard an unrecognized document block.

When a block cannot be converted reliably, preserve its source crop as an image.

======================================================================
12. FORMULA HANDLING
======================================================================

Equation quality is a primary requirement.

Recognize and preserve:

- Inline formulas
- Display formulas
- Fractions
- Roots
- Powers
- Subscripts
- Superscripts
- Greek symbols
- Matrices
- Cases
- Aligned equations
- Multiline equations
- Numbered equations
- Common AMS-style structures
- Chemical notation when recognizable

The recognized LaTeX must remain the source representation.

Use a maintained pure-JavaScript rendering library.

Preferred renderer:

- MathJax in Node.js configured to produce SVG

Do not require a local TeX installation.

For each recognized formula:

1. Extract the LaTeX.
2. Normalize delimiters.
3. Validate that it can be rendered.
4. Generate SVG.
5. Save the SVG as an internal EPUB resource.
6. Embed it in XHTML.
7. Preserve the original LaTeX as accessible alternative text or metadata.

Inline equations:

- Must remain inline.
- Must scale with surrounding text.
- Must not appear as oversized block images.
- Must align reasonably with the text baseline.

Display equations:

- Center them.
- Preserve equation numbers.
- Fit within the available viewport width.
- Avoid clipping.
- Avoid fixed desktop dimensions.
- Remain readable on a six-inch Kobo screen.

Formula fallback order:

1. Generated SVG from recognized LaTeX
2. Original formula crop returned or derivable from PaddleOCR
3. Raw LaTeX shown visibly inside a styled fallback block

Never silently omit a formula.

If formula rendering throws an error:

- Record a non-sensitive diagnostic.
- Use the original crop if available.
- Otherwise display raw LaTeX.
- Continue converting the document.

Do not make the entire conversion fail because one formula is malformed.

Store formula images using deterministic content hashes to deduplicate repeated
formulas.

======================================================================
13. FIGURES AND IMAGE HANDLING
======================================================================

Fix the original repository's image handling.

Do not assume that every image is JPEG.

For each returned resource:

- Download it securely.
- Enforce a maximum resource size.
- Detect the actual format from its file signature.
- Validate that it is a real image.
- Normalize unsupported formats.
- Correct EXIF orientation.
- Remove unnecessary metadata.
- Preserve aspect ratio.
- Avoid unnecessary upscaling.
- Deduplicate identical files by hash.

Use:

- PNG for line art, screenshots, diagrams, formulas, and charts
- JPEG for photographic images
- SVG for generated formulas

Avoid WebP in the generated EPUB for broader reader compatibility.

Rewrite remote and temporary image references to internal EPUB-relative paths.

Use semantic figure markup where supported:

<figure>
  <img src="..." alt="..." />
  <figcaption>...</figcaption>
</figure>

Caption association:

- Use PaddleOCR structure and layout order.
- Associate adjacent Figure/Fig. captions with the nearest corresponding image.
- Preserve figure numbers.
- Keep captions immediately after their figure.
- Do not associate a caption with an unrelated nearby image.
- Use caption text as alt text when appropriate.
- Fall back to "Figure N" or "Document figure" when no caption exists.

Keep figures near the paragraph that introduces them.

Responsive image styling:

- max-width: 100%
- height: auto
- display: block
- margin-left: auto
- margin-right: auto

Avoid page breaks between a figure and caption where the reader supports it.

Never embed external image URLs in the final EPUB.

Every image must be included in the EPUB manifest.

======================================================================
14. TABLE HANDLING
======================================================================

Convert reliable tables into semantic XHTML tables.

Use:

- table
- caption
- thead
- tbody
- tr
- th
- td

Preserve:

- Row order
- Column order
- Header cells
- Captions
- Merged-cell information where representable
- Inline formulas inside cells

Use responsive styling.

Do not assign a fixed width larger than the reading viewport.

For very wide, malformed, or low-confidence tables:

1. Preserve the original table as an image.
2. Preserve its caption.
3. Add extracted text below it when useful.
4. Clearly label the text as a table transcription when appropriate.

Do not flatten a complex table into one unreadable paragraph.

======================================================================
15. EPUB 3 GENERATION
======================================================================

Generate a standards-compliant reflowable EPUB 3.

Do not create a fixed-layout EPUB.

The EPUB archive must contain:

- mimetype
- META-INF/container.xml
- EPUB package document
- Navigation document
- Manifest
- Spine
- XHTML chapters
- CSS
- Figures and images
- SVG formulas
- Cover
- Table of contents
- Metadata

ZIP rules:

- `mimetype` must be the first ZIP entry.
- `mimetype` must contain exactly:
  application/epub+zip
- `mimetype` must be stored without compression.

Generate chapters based on the recognized heading hierarchy.

When no reliable headings exist:

- Create sensible page-range or section divisions.
- Avoid putting an extremely large document into one XHTML file.

Metadata:

- Title
- Author
- Language
- Unique identifier
- Conversion date
- Original filename

Try to detect:

- Title from the first page
- Author from the first page
- Document language

Allow the user to override title and author before conversion.

EPUB CSS must be optimized for Kobo and KOReader:

- Reflowable text
- No forced body font
- No fixed body font size
- Minimal margins
- Comfortable line spacing
- Left-aligned paragraphs
- Responsive images
- Responsive tables
- No desktop-width containers
- No absolute positioning for ordinary content
- Avoid forced page breaks
- Avoid separating captions from figures

Do not use full justification by default.

Footnotes must be linked where possible.

Links must remain clickable.

The table of contents must function.

Use correct media types for every manifest resource.

No manifest item may reference a missing file.

Validate generated EPUBs with EPUBCheck during development and CI.

EPUBCheck does not need to run during every Vercel conversion.

======================================================================
16. PIN ACCESS PROTECTION
======================================================================

This is a personal application protected by an access PIN.

Do not implement user accounts.

The login page should contain:

- PIN field
- Unlock button
- Simple error message

Store only a password hash in an environment variable:

APP_PIN_HASH

Use:

SESSION_SECRET

Hash the PIN using a maintained password-hashing implementation.

Do not store the raw PIN in source code or environment variables.

After successful verification:

- Create a signed session cookie.
- Use HttpOnly.
- Use Secure in production.
- Use SameSite=Lax.
- Default expiration: seven days.
- Provide a logout button.

Protect:

- Upload authorization
- Conversion submission
- Job status
- Finalization
- EPUB download URL generation
- File deletion

Call it a PIN in the interface, but allow a longer numeric or alphanumeric
personal passcode.

Recommend at least eight characters because the URL is publicly accessible.

Use constant-time verification where applicable.

Add:

- robots.txt denying indexing
- X-Robots-Tag: noindex, nofollow
- No sensitive information in page metadata

Do not add a PIN-reset workflow.

======================================================================
17. VERCEL FUNCTION DESIGN
======================================================================

Every Function must remain short-lived.

Suggested routes:

POST /api/auth/login
POST /api/auth/logout
POST /api/upload/authorize
POST /api/jobs/submit
POST /api/jobs/status
POST /api/jobs/finalize
POST /api/jobs/delete
GET  /api/download-url
GET  /api/cleanup

Do not combine all processing into one route.

Configure the Node.js runtime.

Set an appropriate maxDuration only where needed, within the current Hobby
maximum.

Status routes should complete quickly.

The finalize route may:

- Retrieve PaddleOCR results
- Download resources
- Build the EPUB
- Upload the EPUB to private Blob

Initially limit documents so finalization stays comfortably below the Function
duration limit.

If EPUB construction regularly approaches 240 seconds:

- Reduce the maximum pages temporarily.
- Profile the slow operations.
- Do not add a complex queue or paid worker automatically.
- Report the limitation before redesigning the architecture.

Use Vercel's writable /tmp directory only for transient files during one
Function invocation.

Do not assume /tmp persists between invocations.

Write the completed EPUB to Blob before the Function returns.

Return JSON containing a signed download URL, not the EPUB binary itself.

======================================================================
18. RESOURCE AND COST CONTROL
======================================================================

The app should be suitable for approximately:

- Two or three PDF conversions per day
- Typical research papers
- Normal articles
- Occasional scanned chapters

Initial limits:

MAX_PDF_SIZE_MB=50
MAX_PDF_PAGES=100
JOB_EXPIRATION_MINUTES=60
MAX_IMAGE_SIZE_MB=20
MAX_TOTAL_ASSET_MB=300

Keep the limits configurable.

Do not run PaddleOCR more than once for the same active job.

Disable duplicate submission while a job is active.

Do not repeatedly download the same resource.

Use content hashes for deduplication.

Delete files quickly to minimize Blob usage and data transfer.

Add clear handling when:

- Vercel usage limits are exceeded
- Blob storage is unavailable
- PaddleOCR quota is exceeded
- PaddleOCR changes its model availability

Do not add paid services automatically.

======================================================================
19. SECURITY
======================================================================

Validate every API input using Zod or an equivalent schema validator.

Sanitize:

- Filenames
- EPUB metadata
- Markdown HTML
- Image URLs
- Captions
- Links

Prevent:

- Path traversal
- Arbitrary Blob deletion
- SSRF
- Uploading non-PDF files
- Fetching arbitrary untrusted URLs
- HTML/script injection in EPUB content
- Malicious Markdown
- ZIP path traversal
- Oversized decompression payloads

Only download PaddleOCR resources from:

- URLs returned by the authenticated PaddleOCR result
- Expected Paddle/Baidu resource hosts
- Signed Vercel Blob URLs belonging to this project

Apply host allowlisting where practical.

Never log:

- The PIN
- Session cookies
- PaddleOCR token
- PDF contents
- OCR text
- Formula content
- Private Blob signed URLs
- Full upstream responses

Logs may include:

- Job UUID
- Stage
- Duration
- Page count
- Asset count
- Sanitized error category

======================================================================
20. ERROR HANDLING
======================================================================

Use clear errors such as:

- This file is not a valid PDF.
- This PDF is password protected.
- This PDF exceeds the page limit.
- Upload failed.
- PaddleOCR authentication failed.
- PaddleOCR free quota appears to be exhausted.
- Document parsing failed on page N.
- One or more images could not be downloaded.
- EPUB generation failed.
- The conversion expired.
- The temporary file has already been deleted.

Never expose stack traces in production.

Do not silently skip failed pages.

When one page fails:

- Identify the page.
- Allow one retry.
- Preserve the rest of the job state.

When one formula or figure fails:

- Use its fallback.
- Continue the document.
- Include a small conversion warning in the result screen.

Do not insert technical warning text into the EPUB unless content was replaced
with raw fallback data.

======================================================================
21. TESTING
======================================================================

Add unit tests for:

- PIN authentication
- Session-cookie validation
- Job-token signing and verification
- Token expiration
- PDF signature detection
- Filename sanitization
- Blob pathname validation
- PaddleOCR result schema validation
- Markdown AST processing
- Paragraph joining across pages
- Header and footer detection
- Hyphenation repair
- Reading-order preservation
- Formula extraction
- Formula SVG rendering
- Formula crop fallback
- Image MIME detection
- Image normalization
- Image reference rewriting
- Figure-caption association
- Table conversion
- Table-image fallback
- EPUB manifest generation
- EPUB navigation generation
- ZIP mimetype ordering
- Temporary-file cleanup

Create test fixtures covering:

1. Born-digital single-column PDF
2. Born-digital two-column PDF
3. Scanned PDF
4. Paper with inline equations
5. Paper with display equations
6. Paper with matrices
7. Paper with numbered equations
8. Paper with figures and captions
9. Paper with diagrams
10. Paper with complex tables
11. Article saved as PDF
12. Book chapter
13. Mixed-language PDF
14. Password-protected PDF
15. Damaged PDF
16. PDF with missing or malformed image resources

Acceptance criteria:

- The app deploys to Vercel Hobby.
- No local OCR model is downloaded.
- No GPU is required.
- No database is required.
- PDF uploads bypass the 4.5 MB Function-body limit.
- PaddleOCR runs asynchronously.
- The app does not wait for the OCR job inside one Function request.
- EPUBCheck passes for test outputs.
- Every EPUB image reference resolves.
- Every EPUB manifest resource exists.
- Formulas are never silently removed.
- Figures retain their captions.
- Two-column documents read in the correct order.
- The EPUB opens in KOReader.
- The EPUB opens in Kobo's stock reader where supported.
- Temporary documents are deleted.
- No conversion history is retained.
- The application is inaccessible without the PIN session.

======================================================================
22. ENVIRONMENT VARIABLES
======================================================================

Create `.env.example` with:

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

Do not add:

- Database variables
- Google OAuth variables
- Payment variables
- Analytics variables

Provide a small script to generate:

- APP_PIN_HASH
- SESSION_SECRET
- JOB_TOKEN_SECRET
- CRON_SECRET

Do not print secrets after initial creation unless explicitly requested.

======================================================================
23. README
======================================================================

The README must explain:

1. What the application does
2. That PDFs are sent temporarily to Baidu PaddleOCR
3. How to get a PaddleOCR AI Studio access token
4. How to install dependencies
5. How to generate the PIN hash and secrets
6. How to configure Vercel Blob
7. How to run locally
8. How to deploy to Vercel Hobby
9. How temporary deletion works
10. Current file and page limits
11. How to test EPUB output
12. How to run EPUBCheck
13. Common PaddleOCR quota and authentication errors
14. Common Vercel Blob errors
15. How to uninstall/delete all stored files
16. Which upstream repository inspired the implementation
17. Which upstream license notices must remain

Clearly state:

- PaddleOCR's advertised free quota may change.
- Vercel Hobby allowances may change.
- The source PDF is processed by Baidu's hosted service.
- No conversion history is intentionally retained.

======================================================================
24. IMPLEMENTATION ORDER
======================================================================

Before writing code:

1. Inspect the latest version of:
   https://github.com/jarodise/pdf2epub-paddle

2. Inspect the latest official PaddleOCR TypeScript SDK documentation.

3. Inspect the latest official PaddleOCR-VL documentation.

4. Inspect the latest official Vercel Function-limit documentation.

5. Inspect the latest official Vercel Blob client-upload, private-storage, and
   signed-URL documentation.

6. Verify that these still exist:
   - @paddleocr/api-sdk
   - PaddleOCRClient
   - Model.PaddleOCRVL16
   - submitDocumentParsing
   - getStatus
   - waitDocumentParsingResult
   - saveDocumentParsingResultResources

7. Verify the exact PaddleOCR-VL option names.

8. Verify the current result schema.

9. Write a short implementation plan.

Then implement in phases.

Phase 1:

- Project setup
- PIN authentication
- Direct private Blob upload
- PaddleOCR submission
- Signed stateless job token
- Status polling
- Basic Markdown-to-EPUB
- Signed EPUB download
- Cleanup

Phase 2:

- Markdown AST normalization
- Correct reading order
- Formula-to-SVG rendering
- Formula fallbacks
- Image MIME detection
- Figure-caption handling
- Reliable EPUB generation
- EPUBCheck CI

Phase 3:

- Better table handling
- Better page-continuation handling
- Better repeated-header removal
- Cancellation
- Stale Blob cleanup
- Error hardening
- Mobile polish

Do not begin Phase 3 until Phase 1 and Phase 2 tests pass.

======================================================================
SOURCE CONTROL REQUIREMENTS
======================================================================

Use Git from the beginning and commit at every meaningful milestone.

Requirements:

- Initialize the repository before implementation begins.
- Create a new feature branch for the work.
- Keep commits small, focused, and reversible.
- Do not combine unrelated changes in one commit.
- Run tests, linting, and type checking before milestone commits.
- Never commit secrets, access tokens, `.env` files, uploaded PDFs, generated
  EPUBs, Blob URLs, or private test documents.
- Maintain an accurate `.gitignore`.
- Preserve the upstream repository’s license and attribution.

Create commits at minimum after:

1. Initial project setup and dependency installation
2. PIN authentication
3. Direct PDF upload and temporary storage
4. PaddleOCR API submission and status polling
5. Basic EPUB generation
6. Formula rendering and fallbacks
7. Figure, image, and caption handling
8. Table handling
9. Cleanup and deletion logic
10. Tests and EPUBCheck integration
11. Vercel deployment configuration
12. Final documentation and working release

Use descriptive commit messages, for example:

- `chore: initialize Next.js app and preserve upstream license`
- `feat: add PIN-protected session authentication`
- `feat: submit PDFs to PaddleOCR asynchronously`
- `feat: generate basic EPUB 3 output`
- `fix: preserve equations using SVG fallbacks`
- `fix: embed figures with captions and correct MIME types`
- `feat: delete temporary conversion files`
- `test: add EPUB generation and cleanup coverage`
- `docs: add Vercel deployment guide`

Before major refactors or risky changes:

- Commit the current working state first.
- Create a temporary branch if appropriate.
- Do not rewrite shared history.
- Do not use `git reset --hard`, force push, or destructive cleanup unless
  explicitly instructed.

At the end:

- Ensure `git status` is clean.
- Tag the first working version as `v0.1.0`.
- Include a brief commit summary in the final report.

======================================================================
25. DO NOT OVERENGINEER
======================================================================

Do not introduce:

- A database
- A queue service
- A worker platform
- Kubernetes
- Docker deployment
- User accounts
- Cloud synchronization
- Document history
- Notifications
- AI chat
- Summaries
- An editor
- OCR correction UI
- Multiple themes
- Multiple conversion presets
- Commercial functionality

Do not rewrite PaddleOCR.

Do not train a model.

Do not run OCR locally.

Do not build a generic publishing platform.

The finished product should remain:

PIN
→ Upload PDF
→ Convert
→ Download EPUB
→ Delete

======================================================================
26. FINAL DELIVERABLES
======================================================================

Deliver:

- Complete source code
- Preserved upstream licensing
- Strict TypeScript
- Vercel configuration
- Private Blob integration
- PaddleOCR API integration
- PIN authentication
- Stateless job flow
- EPUB 3 generator
- Formula SVG renderer
- Image and figure handling
- Table handling
- Cleanup logic
- Automated tests
- EPUBCheck CI
- `.env.example`
- Deployment README

Before declaring completion:

1. Deploy a working preview.
2. Convert at least one two-column research paper.
3. Convert at least one equation-heavy document.
4. Convert at least one scanned PDF.
5. Open each generated EPUB in KOReader.
6. Validate each EPUB with EPUBCheck.
7. Confirm that temporary source files are deleted.
8. Confirm that no database or conversion history exists.
9. Confirm that the project fits the current Vercel Hobby constraints.
10. Report any remaining known limitations honestly.