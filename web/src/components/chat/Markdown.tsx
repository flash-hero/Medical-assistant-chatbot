"use client";

import { memo, useMemo, type ReactNode } from "react";
import { dirOf } from "@/lib/i18n/text-language";
import { parseMarkdown, type Inline } from "@/lib/markdown/parse";

export interface CitationRef {
  readonly n: number;
  readonly title: string;
}

interface MarkdownProps {
  readonly text: string;
  readonly citations: ReadonlyMap<number, CitationRef>;
  readonly onCite: (n: number, trigger: HTMLButtonElement) => void;
  readonly citeLabel: (n: number, title: string) => string;
  /** Language of `citeLabel` (the UI's) when the text around it is in another language. */
  readonly labelLang?: string;
}

function plainText(nodes: readonly Inline[]): string {
  return nodes.map((node) => (node.type === "text" ? node.value : node.type === "strong" ? plainText(node.children) : "")).join("");
}

/**
 * Renders the restricted Markdown AST with React text nodes only: no dangerouslySetInnerHTML,
 * no links and no images from model text. [n] becomes a button only when citation n exists.
 * Each paragraph and list item takes the direction of its dominant script (review T1), so a
 * French answer on the Arabic page reads left to right and an Arabic line starting "HbA1c" right to left.
 */
function MarkdownImpl({ text, citations, onCite, citeLabel, labelLang }: MarkdownProps) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);

  const renderInline = (nodes: readonly Inline[], keyPrefix: string): ReactNode[] =>
    nodes.map((node, i) => {
      const key = `${keyPrefix}-${i}`;
      if (node.type === "text") return node.value;
      if (node.type === "strong") return <strong key={key}>{renderInline(node.children, key)}</strong>;
      const ref = citations.get(node.n);
      if (!ref) return `[${node.n}]`;
      return (
        <button
          key={key}
          type="button"
          className="cite-chip"
          data-cite={node.n}
          lang={labelLang}
          aria-label={citeLabel(node.n, ref.title)}
          onClick={(e) => onCite(node.n, e.currentTarget)}
        >
          {node.n}
        </button>
      );
    });

  return (
    <div className="prose-answer">
      {blocks.map((block, i) =>
        block.type === "paragraph" ? (
          <p key={`p-${i}`} dir={dirOf(plainText(block.children))}>
            {renderInline(block.children, `p-${i}`)}
          </p>
        ) : (
          <ul key={`l-${i}`} dir={dirOf(block.items.map(plainText).join(" "))}>
            {block.items.map((item, j) => (
              <li key={`l-${i}-${j}`} dir={dirOf(plainText(item))}>
                {renderInline(item, `l-${i}-${j}`)}
              </li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
