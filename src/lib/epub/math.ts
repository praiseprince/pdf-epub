import { mathjax } from "mathjax-full/js/mathjax.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({
  packages: ["base", "ams", "newcommand", "noundefined"]
});
const svg = new SVG({
  fontCache: "none"
});
const html = mathjax.document("", {
  InputJax: tex,
  OutputJax: svg
});

export function normalizeLatex(value: string) {
  return value
    .replace(/^\s*\$\$?/, "")
    .replace(/\$\$?\s*$/, "")
    .replace(/^\s*\\\[/, "")
    .replace(/\\\]\s*$/, "")
    .replace(/^\s*\\\(/, "")
    .replace(/\\\)\s*$/, "")
    .trim();
}

export function renderFormulaSvg(latex: string, display: boolean) {
  const normalized = normalizeLatex(latex);
  const node = html.convert(normalized, {
    display
  });
  const outer = adaptor.outerHTML(node);

  if (!outer.includes("<svg")) {
    throw new Error("Formula SVG rendering failed.");
  }

  return outer.replace(/<mjx-container[^>]*>/, "").replace("</mjx-container>", "");
}

