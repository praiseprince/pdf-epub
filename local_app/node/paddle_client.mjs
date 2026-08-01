import { readFile } from "node:fs/promises";
import { Model, PaddleOCRClient } from "@paddleocr/api-sdk";

const command = process.argv[2];

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
  relevelTitles: true,
};

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
    requestTimeout: 300_000,
    pollTimeout: 3_600_000,
  });
}

async function main() {
  const payload = await readJsonStdin();
  const paddle = client();

  if (command === "submit") {
    const result = await paddle.submitDocumentParsing({
      filePath: payload.filePath,
      model: Model.PaddleOCRVL16,
      options: DEFAULT_OPTIONS,
    });
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "status") {
    const result = await paddle.getStatus(payload.jobId);
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "result") {
    const result = await paddle.waitDocumentParsingResult(payload.jobId);
    console.log(JSON.stringify(result));
    return;
  }

  if (command === "parse") {
    const result = await paddle.parseDocument({
      filePath: payload.filePath,
      model: Model.PaddleOCRVL16,
      options: DEFAULT_OPTIONS,
    });
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
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
