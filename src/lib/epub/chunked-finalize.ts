import { BlobNotFoundError, head, put } from "@vercel/blob";
import type { Root } from "mdast";
import { randomUUID } from "node:crypto";
import { Readable } from "node:stream";
import { ZipFile } from "yazl";
import { deleteJobBlobs } from "@/lib/blob/cleanup";
import {
  finalizeStatePath,
  resultEpubPath,
  stagedChapterPath,
  stagedResourcePath
} from "@/lib/blob/paths";
import { createSignedGetUrl } from "@/lib/blob/signed-url";
import { getPrivateBlobStream, readPrivateBlobText } from "@/lib/blob/io";
import { finalizeChapterBatchSize, finalizeImagePageBatchSize } from "@/lib/config/limits";
import type { JobTokenClaims } from "@/lib/jobs/tokens";
import { docParsingResultSchema } from "@/lib/paddle/schema";
import {
  bookCss,
  collectPageImageReferences,
  containerXml,
  coverDocument,
  type EpubMetadata,
  navDocument,
  packageDocument,
  sanitizeEpubMetadata,
  splitChapters,
  xhtmlDocument
} from "./build";
import { prepareImageResources } from "./images";
import { renderRoot } from "./render";
import { ResourceRegistry } from "./resources";

type StoredChapter = {
  id: string;
  title: string;
  filename: string;
  pageIndexes: number[];
  root: Root;
  contentPath?: string;
};

type StoredResource = {
  href: string;
  mediaType: string;
  path: string;
};

type FinalizePhase = "images" | "chapters" | "packaging" | "complete";

type ChunkedFinalizeState = {
  version: 1;
  jobId: string;
  identifier: string;
  phase: FinalizePhase;
  metadata: EpubMetadata;
  totalPages: number;
  pageImageReferences: Record<string, string>[];
  chapters: StoredChapter[];
  imageMap: Array<[string, string]>;
  resources: StoredResource[];
  warnings: string[];
  nextImagePage: number;
  nextChapterIndex: number;
  createdAt: number;
  updatedAt: number;
};

export type ChunkedFinalizeProgress = {
  label: string;
  processed: number;
  total: number;
};

export type ChunkedFinalizeResult =
  | {
      state: "building";
      stage: string;
      progress: ChunkedFinalizeProgress;
      warnings: string[];
    }
  | {
      state: "ready";
      stage: string;
      progress: ChunkedFinalizeProgress;
      downloadUrl: string;
      warnings: string[];
      outputPath: string;
    };

const STATE_MAX_BYTES = 100 * 1024 * 1024;

function metadataFromClaims(jobClaims: JobTokenClaims) {
  return sanitizeEpubMetadata({
    title: jobClaims.title ?? jobClaims.originalFilename.replace(/\.pdf$/i, ""),
    ...(jobClaims.author ? { author: jobClaims.author } : {}),
    originalFilename: jobClaims.originalFilename
  });
}

function mergeRecords(records: Record<string, string>[]) {
  return records.reduce<Record<string, string>>((merged, record) => ({ ...merged, ...record }), {});
}

function stateProgress(state: ChunkedFinalizeState): ChunkedFinalizeProgress {
  if (state.phase === "images") {
    return {
      label: "Preparing images",
      processed: state.nextImagePage,
      total: state.totalPages
    };
  }

  if (state.phase === "chapters") {
    return {
      label: "Rendering chapters",
      processed: state.nextChapterIndex,
      total: state.chapters.length
    };
  }

  return {
    label: state.phase === "complete" ? "EPUB ready" : "Packaging EPUB",
    processed: state.phase === "complete" ? 1 : 0,
    total: 1
  };
}

function stageForProgress(progress: ChunkedFinalizeProgress) {
  return `${progress.label} (${progress.processed}/${progress.total})`;
}

async function readFinalizeState(jobId: string): Promise<ChunkedFinalizeState | null> {
  try {
    const raw = await readPrivateBlobText(finalizeStatePath(jobId), STATE_MAX_BYTES);
    return JSON.parse(raw) as ChunkedFinalizeState;
  } catch {
    return null;
  }
}

async function writeFinalizeState(state: ChunkedFinalizeState) {
  state.updatedAt = Date.now();
  await put(finalizeStatePath(state.jobId), JSON.stringify(state), {
    access: "private",
    contentType: "application/json",
    allowOverwrite: true,
    cacheControlMaxAge: 0
  });
}

async function existingResult(jobId: string, warnings: string[] = []): Promise<ChunkedFinalizeResult | null> {
  const outputPath = resultEpubPath(jobId);
  try {
    await head(outputPath);
  } catch (error) {
    if (error instanceof BlobNotFoundError) {
      return null;
    }
    throw error;
  }

  return {
    state: "ready",
    stage: "Ready to download",
    progress: {
      label: "EPUB ready",
      processed: 1,
      total: 1
    },
    downloadUrl: await createSignedGetUrl(outputPath, 60 * 60 * 1000),
    warnings,
    outputPath
  };
}

function initialState(rawResult: unknown, jobClaims: JobTokenClaims): ChunkedFinalizeState {
  const result = docParsingResultSchema.parse(rawResult);
  const chapters = splitChapters(result.pages.map((page) => page.markdownText));
  const now = Date.now();

  return {
    version: 1,
    jobId: jobClaims.jobId,
    identifier: `urn:uuid:${randomUUID()}`,
    phase: "images",
    metadata: metadataFromClaims(jobClaims),
    totalPages: result.pages.length,
    pageImageReferences: collectPageImageReferences(result),
    chapters: chapters.map((chapter) => ({
      id: chapter.id,
      title: chapter.title,
      filename: chapter.filename,
      pageIndexes: chapter.pageIndexes,
      root: chapter.root
    })),
    imageMap: [],
    resources: [],
    warnings: [],
    nextImagePage: 0,
    nextChapterIndex: 0,
    createdAt: now,
    updatedAt: now
  };
}

async function uploadResources(jobId: string, state: ChunkedFinalizeState, resources: ResourceRegistry) {
  const existing = new Map(state.resources.map((resource) => [resource.href, resource]));

  for (const resource of resources.all()) {
    const path = stagedResourcePath(jobId, resource.href);
    await put(path, typeof resource.content === "string" ? resource.content : Buffer.from(resource.content), {
      access: "private",
      contentType: resource.mediaType,
      allowOverwrite: true,
      cacheControlMaxAge: 0
    });
    existing.set(resource.href, {
      href: resource.href,
      mediaType: resource.mediaType,
      path
    });
  }

  state.resources = [...existing.values()].sort((left, right) => left.href.localeCompare(right.href));
}

function mergeImageMap(state: ChunkedFinalizeState, imageMap: Map<string, string>) {
  const merged = new Map(state.imageMap);
  for (const entry of imageMap) {
    merged.set(entry[0], entry[1]);
  }
  state.imageMap = [...merged.entries()];
}

async function processImageBatch(state: ChunkedFinalizeState) {
  const start = state.nextImagePage;
  const end = Math.min(state.totalPages, start + finalizeImagePageBatchSize());
  const references = mergeRecords(state.pageImageReferences.slice(start, end));
  const resources = new ResourceRegistry();
  const imageMap = await prepareImageResources(references, resources, state.warnings);

  await uploadResources(state.jobId, state, resources);
  mergeImageMap(state, imageMap);

  state.nextImagePage = end;
  if (state.nextImagePage >= state.totalPages) {
    state.phase = "chapters";
  }
}

async function processChapterBatch(state: ChunkedFinalizeState) {
  const imageMap = new Map(state.imageMap);
  const start = state.nextChapterIndex;
  const end = Math.min(state.chapters.length, start + finalizeChapterBatchSize());

  for (let index = start; index < end; index += 1) {
    const chapter = state.chapters[index];
    if (!chapter) {
      continue;
    }

    const resources = new ResourceRegistry();
    const content = xhtmlDocument(
      chapter.title,
      await renderRoot(chapter.root, {
        resources,
        imageMap,
        warnings: state.warnings,
        chapterId: chapter.id
      })
    );
    const contentPath = stagedChapterPath(state.jobId, chapter.filename);
    await put(contentPath, content, {
      access: "private",
      contentType: "application/xhtml+xml",
      allowOverwrite: true,
      cacheControlMaxAge: 0
    });
    await uploadResources(state.jobId, state, resources);
    chapter.contentPath = contentPath;
  }

  state.nextChapterIndex = end;
  if (state.nextChapterIndex >= state.chapters.length) {
    state.phase = "packaging";
  }
}

function lazyBlobReadStream(blobPath: string) {
  return Readable.from(
    (async function* readBlob() {
      const result = await getPrivateBlobStream(blobPath);
      const reader = result.stream.getReader();

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        yield Buffer.from(value);
      }
    })()
  );
}

function addBlobEntry(zip: ZipFile, path: string, blobPath: string) {
  zip.addReadStream(lazyBlobReadStream(blobPath), path);
}

async function putEpubZip(state: ChunkedFinalizeState) {
  const outputPath = resultEpubPath(state.jobId);
  const zip = new ZipFile();
  const upload = put(outputPath, zip.outputStream as unknown as Readable, {
    access: "private",
    contentType: "application/epub+zip",
    allowOverwrite: true,
    cacheControlMaxAge: 60 * 60
  });

  zip.addBuffer(Buffer.from("application/epub+zip"), "mimetype", { compress: false });
  zip.addBuffer(Buffer.from(containerXml()), "META-INF/container.xml");
  zip.addBuffer(
    Buffer.from(packageDocument(state.metadata, state.identifier, state.chapters, state.resources)),
    "EPUB/package.opf"
  );
  zip.addBuffer(Buffer.from(navDocument(state.metadata, state.chapters)), "EPUB/nav.xhtml");
  zip.addBuffer(Buffer.from(bookCss), "EPUB/styles/book.css");
  zip.addBuffer(Buffer.from(coverDocument(state.metadata)), "EPUB/text/cover.xhtml");

  for (const chapter of state.chapters) {
    if (!chapter.contentPath) {
      throw new Error("EPUB chapter was not staged.");
    }
    addBlobEntry(zip, `EPUB/${chapter.filename}`, chapter.contentPath);
  }

  for (const resource of state.resources) {
    addBlobEntry(zip, `EPUB/${resource.href}`, resource.path);
  }

  zip.end();
  await upload;
  return outputPath;
}

export async function runChunkedFinalizeStep(
  jobClaims: JobTokenClaims,
  loadPaddleResult: () => Promise<unknown>
): Promise<ChunkedFinalizeResult> {
  const ready = await existingResult(jobClaims.jobId);
  if (ready) {
    return ready;
  }

  let state = await readFinalizeState(jobClaims.jobId);
  if (!state) {
    state = initialState(await loadPaddleResult(), jobClaims);
  }

  if (state.phase === "complete") {
    state.phase = "packaging";
  }

  if (state.phase === "images" && state.totalPages === 0) {
    state.phase = "chapters";
  }

  if (state.phase === "images") {
    await processImageBatch(state);
    await writeFinalizeState(state);
    const progress = stateProgress(state);
    return {
      state: "building",
      stage: stageForProgress(progress),
      progress,
      warnings: state.warnings
    };
  }

  if (state.phase === "chapters" && state.chapters.length === 0) {
    state.phase = "packaging";
  }

  if (state.phase === "chapters") {
    await processChapterBatch(state);
    await writeFinalizeState(state);
    const progress = stateProgress(state);
    return {
      state: "building",
      stage: stageForProgress(progress),
      progress,
      warnings: state.warnings
    };
  }

  const outputPath = await putEpubZip(state);
  state.phase = "complete";
  await writeFinalizeState(state);
  await deleteJobBlobs(jobClaims.jobId, false).catch(() => undefined);

  return {
    state: "ready",
    stage: "Ready to download",
    progress: {
      label: "EPUB ready",
      processed: 1,
      total: 1
    },
    downloadUrl: await createSignedGetUrl(outputPath, 60 * 60 * 1000),
    warnings: state.warnings,
    outputPath
  };
}
