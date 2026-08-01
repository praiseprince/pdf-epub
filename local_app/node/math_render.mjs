import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { mathjax } from "mathjax-full/js/mathjax.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import sharp from "sharp";

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({
  packages: ["base", "ams", "newcommand", "noundefined"],
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
  const normalized = String(latex)
    .replace(/\\tag\*\{([^}]*)\}/g, String.raw`\\qquad \\text{$1}`)
    .replace(/\\operatorname\*?\{([^}]*)\}/g, String.raw`\\mathrm{$1}`)
    .replace(/\\_/g, "_");
  const node = html.convert(normalized, { display });
  const outer = adaptor.outerHTML(node);
  if (!outer.includes("<svg") || outer.includes("mjx-merror") || outer.includes("data-mjx-error")) {
    throw new Error("MathJax could not render formula.");
  }
  return outer.replace(/<mjx-container[^>]*>/, "").replace("</mjx-container>", "");
}

async function main() {
  const payload = await readJsonStdin();
  const outputDir = payload.outputDir;
  const formulas = Array.isArray(payload.formulas) ? payload.formulas : [];
  await mkdir(outputDir, { recursive: true });

  const results = [];
  for (const formula of formulas) {
    try {
      const svgText = renderFormulaSvg(String(formula.latex || ""), Boolean(formula.display));
      const target = join(outputDir, String(formula.filename));
      await sharp(Buffer.from(svgText), { density: 220 }).png().toFile(target);
      results.push({ key: formula.key, ok: true, filename: formula.filename });
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
