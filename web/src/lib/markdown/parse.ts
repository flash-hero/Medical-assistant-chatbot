/**
 * Restricted Markdown for model text (core/schemas/events.py): paragraphs, "- " lists, **bold** and
 * [n] citation markers. Everything else (HTML, links, images, headings, code) stays literal text.
 * Output is a small AST rendered by React as text nodes, so nothing is ever parsed as HTML.
 */

export type Inline =
  | { readonly type: "text"; readonly value: string }
  | { readonly type: "strong"; readonly children: readonly Inline[] }
  | { readonly type: "cite"; readonly n: number };

export type Block =
  | { readonly type: "paragraph"; readonly children: readonly Inline[] }
  | { readonly type: "list"; readonly items: readonly (readonly Inline[])[] };

const LIST_ITEM = /^\s*[-•]\s+(.*)$/;
/** [1] or [1, 2] or [1,2,3]: up to three digits per number. */
const CITE_GROUP = /\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/g;

function pushText(out: Inline[], value: string): void {
  if (value === "") return;
  const last = out[out.length - 1];
  if (last?.type === "text") {
    out[out.length - 1] = { type: "text", value: last.value + value };
  } else {
    out.push({ type: "text", value });
  }
}

function appendAll(out: Inline[], nodes: readonly Inline[]): void {
  for (const node of nodes) {
    if (node.type === "text") pushText(out, node.value);
    else out.push(node);
  }
}

function parseCites(text: string): Inline[] {
  const out: Inline[] = [];
  let cursor = 0;
  for (const match of text.matchAll(CITE_GROUP)) {
    const start = match.index ?? 0;
    // "[x](url)" is a Markdown link written by the model: keep it literal.
    if (text[start + match[0].length] === "(") continue;
    pushText(out, text.slice(cursor, start));
    for (const n of (match[1] ?? "").split(",")) out.push({ type: "cite", n: Number.parseInt(n.trim(), 10) });
    cursor = start + match[0].length;
  }
  pushText(out, text.slice(cursor));
  return out;
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    const open = text.indexOf("**", cursor);
    const close = open === -1 ? -1 : text.indexOf("**", open + 2);
    if (open === -1 || close === -1 || close === open + 2) {
      appendAll(out, parseCites(text.slice(cursor)));
      break;
    }
    appendAll(out, parseCites(text.slice(cursor, open)));
    out.push({ type: "strong", children: parseCites(text.slice(open + 2, close)) });
    cursor = close + 2;
  }
  return out;
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let items: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length > 0) blocks.push({ type: "paragraph", children: parseInline(paragraph.join(" ")) });
    paragraph = [];
  };
  const flushList = () => {
    if (items.length > 0) blocks.push({ type: "list", items: items.map(parseInline) });
    items = [];
  };
  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    const item = LIST_ITEM.exec(raw);
    if (line === "") {
      flushParagraph();
      flushList();
    } else if (item) {
      flushParagraph();
      items.push((item[1] ?? "").trim());
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
