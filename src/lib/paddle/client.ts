import {
  Model,
  PaddleOCRClient,
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

function client() {
  return new PaddleOCRClient({
    token: readRequiredEnv("PADDLEOCR_ACCESS_TOKEN"),
    requestTimeout: 60_000,
    pollTimeout: 300_000
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
    client().submitDocumentParsing({
      fileUrl,
      model: Model.PaddleOCRVL16,
      options: DEFAULT_OPTIONS
    })
  );
}

export async function getPaddleStatus(jobId: string): Promise<JobStatus> {
  return withPaddleRetries(() => client().getStatus(jobId), 2);
}

export function mapPaddleError(error: unknown) {
  return toPublicPaddleError(error);
}

