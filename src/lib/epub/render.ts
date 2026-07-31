import type {
  Blockquote,
  Code,
  Content,
  FootnoteDefinition,
  Heading,
  Image,
  InlineCode,
  Link,
  List,
  ListItem,
  Paragraph,
  PhrasingContent,
  Root,
  Table,
  Text
} from "mdast";
import { nodeText } from "./normalize";
import { ResourceRegistry } from "./resources";
import { escapeXml, safeId } from "./xml";
import { renderFormulaSvg } from "./math";

type MathNode = {
  type: "math" | "inlineMath";
  value: string;
};

type FootnoteReferenceNode = {
  type: "footnoteReference";
  identifier: string;
  label?: string;
};

type RenderContext = {
  resources: ResourceRegistry;
  imageMap: Map<string, string>;
  warnings: string[];
  chapterId: string;
  footnotes: Map<string, FootnoteDefinition>;
};

function isMathNode(node: unknown): node is MathNode {
  return (
    typeof node === "object" &&
    node !== null &&
    "type" in node &&
    ((node as { type: string }).type === "math" || (node as { type: string }).type === "inlineMath")
  );
}

function isFootnoteReference(node: unknown): node is FootnoteReferenceNode {
  return typeof node === "object" && node !== null && (node as { type?: string }).type === "footnoteReference";
}

function safeHref(url: string) {
  if (url.startsWith("#")) {
    return url;
  }

  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:" || parsed.protocol === "mailto:") {
      return parsed.toString();
    }
  } catch {
    return "#";
  }

  return "#";
}

async function renderMath(node: MathNode, context: RenderContext) {
  try {
    const display = node.type === "math";
    const svg = renderFormulaSvg(node.value, display);
    const href = context.resources.addHashed("formulas", "svg", "image/svg+xml", svg);
    const alt = escapeXml(node.value);
    if (display) {
      return `<div class="math-block"><img src="../${href}" alt="${alt}" /></div>`;
    }

    return `<img class="math-inline" src="../${href}" alt="${alt}" />`;
  } catch {
    context.warnings.push("One formula could not be rendered as SVG.");
    return `<span class="math-fallback">${escapeXml(node.value)}</span>`;
  }
}

async function renderInline(
  node: PhrasingContent | MathNode | FootnoteReferenceNode,
  context: RenderContext
): Promise<string> {
  if (isMathNode(node)) {
    return renderMath(node, context);
  }

  if (isFootnoteReference(node)) {
    const id = safeId(`${context.chapterId}-fn-${node.identifier}`);
    return `<sup><a href="#${id}" epub:type="noteref">[${escapeXml(node.label ?? node.identifier)}]</a></sup>`;
  }

  switch (node.type) {
    case "text":
      return escapeXml((node as Text).value);
    case "emphasis":
      return `<em>${await renderInlines(node.children, context)}</em>`;
    case "strong":
      return `<strong>${await renderInlines(node.children, context)}</strong>`;
    case "inlineCode":
      return `<code>${escapeXml((node as InlineCode).value)}</code>`;
    case "break":
      return "<br />";
    case "link": {
      const link = node as Link;
      return `<a href="${escapeXml(safeHref(link.url))}">${await renderInlines(link.children, context)}</a>`;
    }
    case "image":
      return renderImage(node as Image, context);
    case "delete":
      return `<del>${await renderInlines(node.children, context)}</del>`;
    default:
      return escapeXml(nodeText(node));
  }
}

async function renderInlines(
  nodes: readonly (PhrasingContent | MathNode | FootnoteReferenceNode)[],
  context: RenderContext
) {
  const rendered = await Promise.all(nodes.map((child) => renderInline(child, context)));
  return rendered.join("");
}

function isImageOnlyParagraph(node: Content): node is Paragraph {
  return node.type === "paragraph" && node.children.length === 1 && node.children[0]?.type === "image";
}

function isCaptionParagraph(node: Content | undefined) {
  if (!node || node.type !== "paragraph") {
    return false;
  }

  return /^(figure|fig\.|table|chart|diagram)\s+\d+/i.test(nodeText(node));
}

function isTableCaptionParagraph(node: Content | undefined) {
  if (!node || node.type !== "paragraph") {
    return false;
  }

  return /^table\s+\d+/i.test(nodeText(node));
}

async function renderImage(node: Image, context: RenderContext) {
  const href = context.imageMap.get(node.url);
  const alt = escapeXml(node.alt || "Document figure");
  if (!href) {
    context.warnings.push("One image was replaced with a fallback.");
    return `<span class="image-fallback">${alt}</span>`;
  }

  return `<img src="${escapeXml(href)}" alt="${alt}" />`;
}

async function renderBlock(node: Content, context: RenderContext): Promise<string> {
  if (isMathNode(node)) {
    return renderMath(node, context);
  }

  switch (node.type) {
    case "heading": {
      const heading = node as Heading;
      const depth = Math.min(6, Math.max(1, heading.depth));
      return `<h${depth}>${await renderInlines(heading.children, context)}</h${depth}>`;
    }
    case "paragraph":
      if (
        (node as Paragraph).children.length === 1 &&
        isMathNode((node as Paragraph).children[0]) &&
        ((node as Paragraph).children[0] as MathNode).type === "inlineMath"
      ) {
        return renderMath({ ...((node as Paragraph).children[0] as MathNode), type: "math" }, context);
      }
      return `<p>${await renderInlines((node as Paragraph).children, context)}</p>`;
    case "blockquote":
      return `<blockquote>${(await Promise.all((node as Blockquote).children.map((child) => renderBlock(child, context)))).join("")}</blockquote>`;
    case "list": {
      const list = node as List;
      const tag = list.ordered ? "ol" : "ul";
      return `<${tag}>${(await Promise.all(list.children.map((item) => renderListItem(item, context)))).join("")}</${tag}>`;
    }
    case "code": {
      const code = node as Code;
      const language = code.lang ? ` class="language-${escapeXml(code.lang)}"` : "";
      return `<pre><code${language}>${escapeXml(code.value)}</code></pre>`;
    }
    case "thematicBreak":
      return "<hr />";
    case "table":
      return renderTable(node as Table, context);
    case "html":
      return `<p>${escapeXml(nodeText(node))}</p>`;
    case "footnoteDefinition":
      context.footnotes.set((node as FootnoteDefinition).identifier, node as FootnoteDefinition);
      return "";
    default:
      return `<p>${escapeXml(nodeText(node))}</p>`;
  }
}

async function renderListItem(node: ListItem, context: RenderContext) {
  return `<li>${(await Promise.all(node.children.map((child) => renderBlock(child, context)))).join("")}</li>`;
}

async function renderTable(node: Table, context: RenderContext, caption?: string) {
  const rows = await Promise.all(
    node.children.map(async (row, rowIndex) => {
      const cellTag = rowIndex === 0 ? "th" : "td";
      const cells = await Promise.all(
        row.children.map(async (cell) => `<${cellTag}>${await renderInlines(cell.children, context)}</${cellTag}>`)
      );
      return `<tr>${cells.join("")}</tr>`;
    })
  );

  const [head, ...body] = rows;
  return `<table>${caption ? `<caption>${caption}</caption>` : ""}${head ? `<thead>${head}</thead>` : ""}<tbody>${body.join("")}</tbody></table>`;
}

async function renderFootnotes(context: RenderContext) {
  if (context.footnotes.size === 0) {
    return "";
  }

  const items: string[] = [];
  for (const [identifier, definition] of context.footnotes) {
    const id = safeId(`${context.chapterId}-fn-${identifier}`);
    const body = (
      await Promise.all(definition.children.map((child) => renderBlock(child as Content, context)))
    ).join("");
    items.push(`<li id="${id}">${body}</li>`);
  }

  return `<section epub:type="footnotes"><h2>Notes</h2><ol>${items.join("")}</ol></section>`;
}

export async function renderRoot(root: Root, context: Omit<RenderContext, "footnotes">) {
  const fullContext: RenderContext = {
    ...context,
    footnotes: new Map()
  };
  const out: string[] = [];
  const children = root.children;

  for (let index = 0; index < children.length; index += 1) {
    const node = children[index];
    if (!node) continue;

    if (isImageOnlyParagraph(node)) {
      const next = children[index + 1];
      const image = await renderImage(node.children[0] as Image, fullContext);
      if (isCaptionParagraph(next)) {
        out.push(
          `<figure>${image}<figcaption>${await renderInlines((next as Paragraph).children, fullContext)}</figcaption></figure>`
        );
        index += 1;
      } else {
        out.push(`<figure>${image}</figure>`);
      }
      continue;
    }

    if (node.type === "table" && isTableCaptionParagraph(children[index + 1])) {
      const caption = await renderInlines((children[index + 1] as Paragraph).children, fullContext);
      out.push(await renderTable(node as Table, fullContext, caption));
      index += 1;
      continue;
    }

    out.push(await renderBlock(node, fullContext));
  }

  out.push(await renderFootnotes(fullContext));
  return out.join("\n");
}
