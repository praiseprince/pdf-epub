import { ZipFile } from "yazl";
import type { Content, Root } from "mdast";
import { randomUUID } from "node:crypto";
import { docParsingResultSchema, type SafeDocParsingResult } from "@/lib/paddle/schema";
import { sanitizeMetadataText } from "@/lib/files/sanitize";
import { nodeText, normalizeMarkdownPages, parseMarkdown } from "./normalize";
import { prepareImageResources } from "./images";
import { renderRoot } from "./render";
import { ResourceRegistry, type EpubResource } from "./resources";
import { escapeXml } from "./xml";

export type EpubMetadata = {
  title: string;
  author?: string;
  language?: string;
  originalFilename: string;
};

export type EpubBuildResult = {
  buffer: Buffer;
  warnings: string[];
};

type Chapter = {
  id: string;
  title: string;
  root: Root;
  filename: string;
  content?: string;
};

const bookCss = `
body {
  line-height: 1.55;
  margin: 0.8em;
  text-align: left;
}
p { margin: 0 0 0.85em; }
h1, h2, h3, h4, h5, h6 { line-height: 1.2; margin: 1.2em 0 0.55em; }
a { color: inherit; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; }
figure { margin: 1em 0; page-break-inside: avoid; break-inside: avoid; }
figcaption { font-size: 0.9em; line-height: 1.35; margin-top: 0.4em; }
.math-inline { display: inline; margin: 0 0.08em; vertical-align: -0.2em; max-height: 1.4em; }
.math-block { text-align: center; overflow-x: auto; margin: 1em 0; }
.math-block img { display: inline-block; max-width: 100%; }
.math-fallback, .image-fallback { border: 1px solid #999; padding: 0.1em 0.25em; }
table { border-collapse: collapse; width: 100%; max-width: 100%; margin: 1em 0; font-size: 0.92em; }
th, td { border: 1px solid #999; padding: 0.3em 0.45em; vertical-align: top; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 0.75em; border: 1px solid #aaa; }
code { font-family: monospace; }
blockquote { margin: 1em 1.2em; }
`.trim();

function collectImageReferences(result: SafeDocParsingResult) {
  const refs: Record<string, string> = {};
  for (const page of result.pages) {
    Object.assign(refs, page.markdownImages, page.outputImages);
  }
  return refs;
}

function splitChapters(markdownPages: string[]) {
  const normalized = normalizeMarkdownPages(markdownPages);
  const chapters: Chapter[] = [];
  let currentChildren: Content[] = [];
  let currentTitle = "Start";
  let foundHeading = false;

  function pushChapter() {
    if (currentChildren.length === 0) {
      return;
    }

    const chapterNumber = chapters.length + 1;
    chapters.push({
      id: `chapter-${chapterNumber}`,
      title: sanitizeMetadataText(currentTitle, `Chapter ${chapterNumber}`),
      root: { type: "root", children: currentChildren },
      filename: `text/chapter-${chapterNumber}.xhtml`
    });
    currentChildren = [];
  }

  for (const page of normalized) {
    const root = parseMarkdown(page.markdown);
    for (const child of root.children) {
      if (child.type === "heading" && child.depth <= 2) {
        foundHeading = true;
        if (currentChildren.length > 0) {
          pushChapter();
        }
        currentTitle = nodeText(child) || `Chapter ${chapters.length + 1}`;
      }
      currentChildren.push(child);
    }

    if (!foundHeading && currentChildren.length > 0 && (page.index + 1) % 10 === 0) {
      currentTitle = `Pages ${page.index - 8}-${page.index + 1}`;
      pushChapter();
    }
  }

  pushChapter();

  if (chapters.length === 0) {
    chapters.push({
      id: "chapter-1",
      title: "Document",
      root: { type: "root", children: [] },
      filename: "text/chapter-1.xhtml"
    });
  }

  return chapters;
}

function xhtmlDocument(title: string, body: string) {
  return `<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
  <meta charset="utf-8" />
  <title>${escapeXml(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/book.css" />
</head>
<body>
${body}
</body>
</html>`;
}

function coverDocument(metadata: Required<Pick<EpubMetadata, "title" | "originalFilename">> & Pick<EpubMetadata, "author">) {
  return xhtmlDocument(
    metadata.title,
    `<section epub:type="cover">
  <h1>${escapeXml(metadata.title)}</h1>
  ${metadata.author ? `<p>${escapeXml(metadata.author)}</p>` : ""}
  <p>Converted from ${escapeXml(metadata.originalFilename)}</p>
</section>`
  );
}

function navDocument(metadata: EpubMetadata, chapters: Chapter[]) {
  const items = chapters
    .map((chapter) => `<li><a href="${escapeXml(chapter.filename)}">${escapeXml(chapter.title)}</a></li>`)
    .join("");
  return `<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head><meta charset="utf-8" /><title>Contents</title></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>${escapeXml(metadata.title)}</h1>
  <ol>${items}</ol>
</nav>
</body>
</html>`;
}

function packageDocument(
  metadata: EpubMetadata,
  identifier: string,
  chapters: Chapter[],
  resources: EpubResource[]
) {
  const modified = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const manifestResources = resources
    .map(
      (resource, index) =>
        `<item id="res-${index + 1}" href="${escapeXml(resource.href)}" media-type="${escapeXml(resource.mediaType)}" />`
    )
    .join("\n");
  const chapterItems = chapters
    .map(
      (chapter) =>
        `<item id="${chapter.id}" href="${escapeXml(chapter.filename)}" media-type="application/xhtml+xml" />`
    )
    .join("\n");
  const spine = chapters.map((chapter) => `<itemref idref="${chapter.id}" />`).join("\n");

  return `<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">${escapeXml(identifier)}</dc:identifier>
    <dc:title>${escapeXml(metadata.title)}</dc:title>
    ${metadata.author ? `<dc:creator>${escapeXml(metadata.author)}</dc:creator>` : ""}
    <dc:language>${escapeXml(metadata.language ?? "en")}</dc:language>
    <dc:source>${escapeXml(metadata.originalFilename)}</dc:source>
    <meta property="dcterms:modified">${modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="css" href="styles/book.css" media-type="text/css" />
    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml" />
    ${chapterItems}
    ${manifestResources}
  </manifest>
  <spine>
    <itemref idref="cover" />
    ${spine}
  </spine>
</package>`;
}

function containerXml() {
  return `<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>`;
}

async function zipEntries(entries: Array<{ path: string; content: Uint8Array | string; compress?: boolean }>) {
  const zip = new ZipFile();
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    zip.outputStream.on("data", (chunk: Buffer) => chunks.push(chunk));
    zip.outputStream.on("error", reject);
    zip.outputStream.on("end", () => resolve(Buffer.concat(chunks)));
  });

  for (const entry of entries) {
    const content = typeof entry.content === "string" ? Buffer.from(entry.content) : Buffer.from(entry.content);
    zip.addBuffer(content, entry.path, { compress: entry.compress ?? true });
  }

  zip.end();
  return done;
}

export async function buildEpubFromPaddleResult(
  rawResult: unknown,
  metadataInput: EpubMetadata
): Promise<EpubBuildResult> {
  const result = docParsingResultSchema.parse(rawResult);
  const warnings: string[] = [];
  const metadata: EpubMetadata = {
    title: sanitizeMetadataText(metadataInput.title, "Untitled document"),
    author: sanitizeMetadataText(metadataInput.author),
    language: metadataInput.language ?? "en",
    originalFilename: sanitizeMetadataText(metadataInput.originalFilename, "document.pdf")
  };
  const resources = new ResourceRegistry();
  const imageMap = await prepareImageResources(collectImageReferences(result), resources, warnings);
  const chapters = splitChapters(result.pages.map((page) => page.markdownText));

  for (const chapter of chapters) {
    chapter.content = xhtmlDocument(
      chapter.title,
      await renderRoot(chapter.root, {
        resources,
        imageMap,
        warnings,
        chapterId: chapter.id
      })
    );
  }

  const resourceItems = resources.all();
  const identifier = `urn:uuid:${randomUUID()}`;
  const entries: Array<{ path: string; content: Uint8Array | string; compress?: boolean }> = [
    { path: "mimetype", content: "application/epub+zip", compress: false },
    { path: "META-INF/container.xml", content: containerXml() },
    { path: "EPUB/package.opf", content: packageDocument(metadata, identifier, chapters, resourceItems) },
    { path: "EPUB/nav.xhtml", content: navDocument(metadata, chapters) },
    { path: "EPUB/styles/book.css", content: bookCss },
    { path: "EPUB/text/cover.xhtml", content: coverDocument(metadata) },
    ...chapters.map((chapter) => ({
      path: `EPUB/${chapter.filename}`,
      content: chapter.content ?? ""
    })),
    ...resourceItems.map((resource) => ({
      path: `EPUB/${resource.href}`,
      content: resource.content
    }))
  ];

  return {
    buffer: await zipEntries(entries),
    warnings
  };
}

export function firstZipEntryIsStoredMimetype(buffer: Uint8Array) {
  const filenameLength = (buffer[26] ?? 0) | ((buffer[27] ?? 0) << 8);
  const extraLength = (buffer[28] ?? 0) | ((buffer[29] ?? 0) << 8);
  const filename = new TextDecoder().decode(buffer.subarray(30, 30 + filenameLength));
  const compressionMethod = (buffer[8] ?? 0) | ((buffer[9] ?? 0) << 8);
  const contentStart = 30 + filenameLength + extraLength;
  const content = new TextDecoder().decode(buffer.subarray(contentStart, contentStart + 20));

  return filename === "mimetype" && compressionMethod === 0 && content === "application/epub+zip";
}
