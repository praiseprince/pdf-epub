import { mathjax } from "mathjax-full/js/mathjax.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { SerializedMmlVisitor } from "mathjax-full/js/core/MmlTree/SerializedMmlVisitor.js";

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
const visitor = new SerializedMmlVisitor(html.mmlFactory);

async function readJsonStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = Buffer.concat(chunks).toString("utf8").trim();
  return input ? JSON.parse(input) : {};
}

function renderFormulaMathml(latex, display) {
  const source = String(latex).trim();
  if (!source) throw new Error("Formula is empty.");
  const root = tex.compile({ math: source, display: Boolean(display), inputData: {} }, html);
  const mathml = visitor.visitTree(root);
  if (mathml.includes("<merror") || mathml.includes("data-mjx-error")) {
    const message = mathml.match(/data-mjx-error="([^"]+)"/)?.[1] || "MathJax could not convert formula to MathML.";
    throw new Error(message);
  }
  return mathml.replace(/\n\s*/g, "");
}

async function main() {
  const payload = await readJsonStdin();
  const formulas = Array.isArray(payload.formulas) ? payload.formulas : [];
  const results = [];

  for (const formula of formulas) {
    try {
      results.push({
        key: formula.key,
        ok: true,
        mathml: renderFormulaMathml(String(formula.latex || ""), Boolean(formula.display)),
      });
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
