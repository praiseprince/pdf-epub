import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { PDFDocument } from "pdf-lib";

type TestsetItem = {
  id: string;
  type: "pdf" | "html-pdf" | "screenshot-pdf";
  filename: string;
  url: string;
  description: string;
};

type TestsetManifest = {
  outputDirectory: string;
  items: TestsetItem[];
};

const root = process.cwd();
const force = process.argv.includes("--force");
const manifestPath = resolve(root, "testsets/manifest.json");
const screenshotDirectory = resolve(root, "testsets/screenshots");

async function readManifest() {
  const json = await readFile(manifestPath, "utf8");
  return JSON.parse(json) as TestsetManifest;
}

function chromeExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  ].filter(Boolean) as string[];

  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) {
    throw new Error("Chrome, Chromium, or Edge is required for HTML-to-PDF test fixtures.");
  }

  return found;
}

async function run(command: string, args: string[], timeoutMs = 90_000) {
  await new Promise<void>((resolvePromise, reject) => {
    const child = spawn(command, args, {
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 5_000).unref();
    }, timeoutMs);

    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolvePromise();
        return;
      }

      reject(
        new Error(
          timedOut
            ? `${command} timed out after ${timeoutMs / 1000}s.`
            : stderr.trim() || `${command} exited with status ${code ?? "unknown"}.`
        )
      );
    });
  });
}

async function downloadPdf(item: TestsetItem, outputPath: string) {
  if (!force && existsSync(outputPath)) {
    console.log(`keep ${item.filename}`);
    return;
  }

  const response = await fetch(item.url, {
    signal: AbortSignal.timeout(120_000)
  });
  if (!response.ok) {
    throw new Error(`Failed to download ${item.id}: ${response.status}`);
  }

  const bytes = new Uint8Array(await response.arrayBuffer());
  const header = new TextDecoder().decode(bytes.slice(0, 5));
  if (header !== "%PDF-") {
    throw new Error(`${item.id} did not return a PDF.`);
  }

  await writeFile(outputPath, bytes);
  console.log(`wrote ${item.filename} (${(bytes.byteLength / 1024 / 1024).toFixed(1)} MB)`);
}

async function printHtmlToPdf(item: TestsetItem, outputPath: string) {
  if (!force && existsSync(outputPath)) {
    console.log(`keep ${item.filename}`);
    return;
  }

  const chrome = chromeExecutable();
  const profilePath = resolve(root, "tmp", `chrome-${item.id}`);
  await mkdir(dirname(profilePath), { recursive: true });
  await run(chrome, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--disable-extensions",
    `--user-data-dir=${profilePath}`,
    "--print-to-pdf-no-header",
    `--print-to-pdf=${outputPath}`,
    item.url
  ]);
  console.log(`printed ${item.filename}`);
}

async function screenshotToPdf(item: TestsetItem, outputPath: string) {
  if (!force && existsSync(outputPath)) {
    console.log(`keep ${item.filename}`);
    return;
  }

  const chrome = chromeExecutable();
  const screenshotPath = join(screenshotDirectory, `${item.id}.png`);
  const profilePath = resolve(root, "tmp", `chrome-${item.id}`);
  await mkdir(screenshotDirectory, { recursive: true });
  await run(chrome, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--disable-extensions",
    "--hide-scrollbars",
    "--window-size=1280,1800",
    `--user-data-dir=${profilePath}`,
    `--screenshot=${screenshotPath}`,
    item.url
  ]);

  const pngBytes = await readFile(screenshotPath);
  const document = await PDFDocument.create();
  const image = await document.embedPng(pngBytes);
  const page = document.addPage([612, 792]);
  const scale = Math.min(560 / image.width, 740 / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  page.drawImage(image, {
    x: (612 - width) / 2,
    y: (792 - height) / 2,
    width,
    height
  });
  await writeFile(outputPath, await document.save());
  console.log(`created ${item.filename}`);
}

async function main() {
  const manifest = await readManifest();
  const outputDirectory = resolve(root, manifest.outputDirectory);
  await mkdir(outputDirectory, { recursive: true });

  for (const item of manifest.items) {
    const outputPath = join(outputDirectory, item.filename);
    if (item.type === "pdf") {
      await downloadPdf(item, outputPath);
    } else if (item.type === "html-pdf") {
      await printHtmlToPdf(item, outputPath);
    } else {
      await screenshotToPdf(item, outputPath);
    }
  }

  console.log(`Test PDFs are ready in ${manifest.outputDirectory}.`);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Failed to prepare testset.");
  process.exitCode = 1;
});
