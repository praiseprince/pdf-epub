import {
  Model,
  PaddleOCRClient,
  type DocParsingResult,
  type Job,
  type JobStatus,
  type PaddleOCRVLOptions
} from "@paddleocr/api-sdk";
import { readRequiredEnv } from "@/lib/server/env";
import { toPublicPaddleError } from "./errors";

const DEFAULT_OPTIONS = {
  useDocOrientationClassify: true,
  useDocUnwarping: true,
  useLayoutDetection: true,
  useChartRecognition: true,
  prettifyMarkdown: true,
  returnMarkdownImages: true,
  showFormulaNumber: true,
  restructurePages: true,
  mergeTables: true,
  relevelTitles: true
} satisfies PaddleOCRVLOptions;

function client(requestTimeout = 60_000, pollTimeout = 300_000) {
  return new PaddleOCRClient({
    token: readRequiredEnv("PADDLEOCR_ACCESS_TOKEN"),
    requestTimeout,
    pollTimeout
  });
}

async function withPaddleRetries<T>(operation: () => Promise<T>, attempts = 3): Promise<T> {
  let lastError: unknown;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      const publicError = toPublicPaddleError(error);
      if (!publicError.retryable || attempt === attempts - 1) {
        throw error;
      }

      await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    }
  }

  throw lastError;
}

export async function submitPaddleDocument(fileUrl: string): Promise<Job> {
  return withPaddleRetries(() =>
    client(90_000, 90_000).submitDocumentParsing({
      fileUrl,
      model: Model.PaddleOCRVL16,
      options: DEFAULT_OPTIONS
    }),
    2
  );
}

export async function getPaddleStatus(jobId: string): Promise<JobStatus> {
  return withPaddleRetries(() => client(10_000, 10_000).getStatus(jobId), 2);
}

export async function getPaddleDocumentResult(jobId: string): Promise<DocParsingResult> {
  return withPaddleRetries(() => client(120_000, 120_000).waitDocumentParsingResult(jobId), 2);
}

export function mapPaddleError(error: unknown) {
  return toPublicPaddleError(error);
}
