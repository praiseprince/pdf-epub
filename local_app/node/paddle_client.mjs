import { readFile } from "node:fs/promises";
import { Model, PaddleOCRClient } from "@paddleocr/api-sdk";

const command = process.argv[2];

const DEFAULT_VL_OPTIONS = {
  useDocOrientationClassify: true,
  useDocUnwarping: true,
  useLayoutDetection: true,
  useChartRecognition: true,
  prettifyMarkdown: true,
  returnMarkdownImages: true,
  showFormulaNumber: true,
  restructurePages: true,
  mergeTables: true,
  relevelTitles: true,
};

const DEFAULT_STRUCTURE_OPTIONS = {
  useDocOrientationClassify: true,
  useDocUnwarping: true,
  useTextlineOrientation: true,
  useTableRecognition: true,
  useFormulaRecognition: true,
  useChartRecognition: true,
  useRegionDetection: true,
  formatBlockContent: true,
  prettifyMarkdown: true,
  returnMarkdownImages: true,
  showFormulaNumber: true,
};

function intEnv(name, fallback) {
  const value = Number.parseInt(process.env[name] || "", 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function defaultOptions(model) {
  return model === Model.PPStructureV3 ? DEFAULT_STRUCTURE_OPTIONS : DEFAULT_VL_OPTIONS;
}

function requestFromPayload(payload) {
  const model = payload.model || process.env.PADDLEOCR_MODEL || Model.PaddleOCRVL16;
  return {
    model,
    options: payload.options || defaultOptions(model),
    pageRanges: payload.pageRanges,
    batchId: payload.batchId,
    ...(payload.fileUrl ? { fileUrl: payload.fileUrl } : { filePath: payload.filePath }),
  };
}

async function readJsonStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = Buffer.concat(chunks).toString("utf8").trim();
  return input ? JSON.parse(input) : {};
}

function client() {
  return new PaddleOCRClient({
    token: process.env.PADDLEOCR_ACCESS_TOKEN,
    requestTimeout: intEnv("PADDLEOCR_REQUEST_TIMEOUT_MS", 300_000),
    pollTimeout: intEnv("PADDLEOCR_POLL_TIMEOUT_MS", 3_600_000),
  });
}

async function main() {
  const payload = await readJsonStdin();
  const paddle = client();

  if (command === "submit") {
    const result = await paddle.submitDocumentParsing(requestFromPayload(payload));
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "status") {
    const result = await paddle.getStatus(payload.jobId);
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "result") {
    const model = payload.model || process.env.PADDLEOCR_MODEL || Model.PaddleOCRVL16;
    const result = await paddle.waitDocumentParsingResult({
      jobId: payload.jobId,
      model,
      task: "document_parsing",
      pageRanges: payload.pageRanges,
      batchId: payload.batchId,
    });
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "parse") {
    const result = await paddle.parseDocument(requestFromPayload(payload));
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "fixture-file") {
    const result = JSON.parse(await readFile(payload.path, "utf8"));
    console.log(JSON.stringify(result));
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  console.error(
    JSON.stringify({
      name: error?.name || "Error",
      message: error instanceof Error ? error.message : String(error),
      timeoutMs: error?.timeoutMs,
      statusCode: error?.statusCode,
    })
  );
  process.exitCode = 1;
});
