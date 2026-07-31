import { toString } from "mdast-util-to-string";
import type { Root } from "mdast";
import { unified } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";

export type NormalizedPage = {
  index: number;
  markdown: string;
};

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);
const terminalPattern = /[.!?。！？)"'\]]$/;
const specialLinePattern =
  /^(#{1,6}\s|>\s|[-*+]\s|\d+[.)]\s|```|~~~|\|.*\||!\[| {0,3}([-*_])(?:\s*\2){2,}\s*$)/;

function normalizeLine(line: string) {
  return line.replace(/\s+/g, " ").trim().toLowerCase();
}

function topBottomRepeatedLines(pages: string[]) {
  const top = new Map<string, number>();
  const bottom = new Map<string, number>();

  for (const markdown of pages) {
    const lines = markdown
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    for (const candidate of lines.slice(0, 2)) {
      const key = normalizeLine(candidate);
      if (key) top.set(key, (top.get(key) ?? 0) + 1);
    }
    for (const candidate of lines.slice(-2)) {
      const key = normalizeLine(candidate);
      if (key) bottom.set(key, (bottom.get(key) ?? 0) + 1);
    }
  }

  const threshold = Math.max(3, Math.ceil(pages.length * 0.5));
  return {
    top,
    bottom,
    threshold
  };
}

function isStandalonePageNumber(line: string) {
  return /^\s*(?:-?\s*)?\d{1,4}\s*(?:-?\s*)?$/.test(line);
}

function repairHyphenation(left: string, right: string) {
  if (/[A-Za-z]{3,}-$/.test(left) && /^[a-z]{2,}/.test(right)) {
    return `${left.slice(0, -1)}${right}`;
  }

  return `${left} ${right}`;
}

function reflowMarkdown(markdown: string) {
  const lines = markdown.split(/\r?\n/);
  const out: string[] = [];
  let paragraph = "";
  let inFence = false;

  function flush() {
    if (paragraph) {
      out.push(paragraph);
      paragraph = "";
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();

    if (/^(```|~~~)/.test(trimmed)) {
      flush();
      inFence = !inFence;
      out.push(line);
      continue;
    }

    if (inFence) {
      out.push(line);
      continue;
    }

    if (!trimmed) {
      flush();
      if (out.at(-1) !== "") {
        out.push("");
      }
      continue;
    }

    if (specialLinePattern.test(trimmed)) {
      flush();
      out.push(line);
      continue;
    }

    if (!paragraph) {
      paragraph = trimmed;
    } else if (terminalPattern.test(paragraph)) {
      out.push(paragraph);
      paragraph = trimmed;
    } else {
      paragraph = repairHyphenation(paragraph, trimmed);
    }
  }

  flush();
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function normalizeMarkdownPages(markdownPages: string[]): NormalizedPage[] {
  const repeated = topBottomRepeatedLines(markdownPages);

  return markdownPages.map((markdown, index) => {
    const lines = markdown.split(/\r?\n/);
    const cleaned = lines.filter((line, lineIndex) => {
      const key = normalizeLine(line);
      if (!key) return true;
      if (isStandalonePageNumber(line)) return false;
      const nearTop = lineIndex < 2;
      const nearBottom = lineIndex >= lines.length - 2;
      if (nearTop && (repeated.top.get(key) ?? 0) >= repeated.threshold) return false;
      if (nearBottom && (repeated.bottom.get(key) ?? 0) >= repeated.threshold) return false;
      return true;
    });

    return {
      index,
      markdown: reflowMarkdown(cleaned.join("\n"))
    };
  });
}

export function parseMarkdown(markdown: string) {
  return parser.parse(markdown) as Root;
}

export function nodeText(node: unknown) {
  return toString(node as never).trim();
}

