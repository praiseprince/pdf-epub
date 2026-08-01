import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { mathjax } from "mathjax-full/js/mathjax.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import sharp from "sharp";

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({
  packages: AllPackages,
});
const svg = new SVG({
  fontCache: "none",
});
const html = mathjax.document("", {
  InputJax: tex,
  OutputJax: svg,
});

async function readJsonStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = Buffer.concat(chunks).toString("utf8").trim();
  return input ? JSON.parse(input) : {};
}

function renderFormulaSvg(latex, display) {
  let lastError = null;
  for (const candidate of formulaCandidates(latex)) {
    try {
      const node = html.convert(candidate, { display });
      const outer = adaptor.outerHTML(node);
      if (!outer.includes("<svg") || outer.includes("mjx-merror") || outer.includes("data-mjx-error")) {
        throw new Error("MathJax could not render formula.");
      }
      return {
        svg: sizeSvgForPng(outer.replace(/<mjx-container[^>]*>/, "").replace("</mjx-container>", ""), display),
        repaired: candidate !== String(latex),
      };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("MathJax could not render formula.");
}

function formulaCandidates(latex) {
  const source = String(latex).trim();
  const normalized = source
    .replace(/\u2212/g, "-")
    .replace(/\\tag\*\{([^}]*)\}/g, String.raw`\qquad \text{$1}`)
    .replace(/\\operatorname\*?\{([^}]*)\}/g, String.raw`\mathrm{$1}`)
    .replace(/\\_/g, "_");
  return [...new Set([source, normalized])].filter(Boolean);
}

function sizeSvgForPng(svgText, display) {
  const outerSvg = svgText.match(/^<svg\b[^>]*>/)?.[0] || "";
  const exWidth = outerSvg.match(/min-width:\s*([0-9.]+)ex/) || outerSvg.match(/\swidth="([0-9.]+)ex"/);
  const exHeight = outerSvg.match(/\sheight="([0-9.]+)ex"/);
  if (exWidth && exHeight) {
    const exPixels = display ? 22 : 18;
    const minHeight = display ? 44 : 24;
    const width = Math.max(24, Math.ceil(Number.parseFloat(exWidth[1]) * exPixels));
    const height = Math.max(minHeight, Math.ceil(Number.parseFloat(exHeight[1]) * exPixels));
    return replaceSvgSize(svgText, width, height);
  }

  const viewBox = outerSvg.match(/viewBox="([^"]+)"/);
  if (!viewBox) return svgText;
  const parts = viewBox[1].split(/\s+/).map((value) => Number.parseFloat(value));
  if (parts.length !== 4 || parts.some((value) => !Number.isFinite(value))) return svgText;
  const [, , viewWidth, viewHeight] = parts;
  const scale = display ? 0.08 : 0.055;
  const minHeight = display ? 44 : 24;
  const width = Math.max(24, Math.ceil(viewWidth * scale));
  const height = Math.max(minHeight, Math.ceil(viewHeight * scale));
  return replaceSvgSize(svgText, width, height);
}

function replaceSvgSize(svgText, width, height) {
  return svgText
    .replace(/\swidth="[^"]*"/, ` width="${width}"`)
    .replace(/\sheight="[^"]*"/, ` height="${height}"`);
}

async function main() {
  const payload = await readJsonStdin();
  const outputDir = payload.outputDir;
  const formulas = Array.isArray(payload.formulas) ? payload.formulas : [];
  await mkdir(outputDir, { recursive: true });

  const results = [];
  for (const formula of formulas) {
    try {
      const rendered = renderFormulaSvg(String(formula.latex || ""), Boolean(formula.display));
      const target = join(outputDir, String(formula.filename));
      await sharp(Buffer.from(rendered.svg)).flatten({ background: "#ffffff" }).png().toFile(target);
      results.push({ key: formula.key, ok: true, filename: formula.filename, repaired: rendered.repaired });
    } catch (error) {
      results.push({
        key: formula.key,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  console.log(JSON.stringify({ results }));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
