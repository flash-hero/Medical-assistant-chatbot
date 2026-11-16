"use client";

import { memo, useMemo, type ReactNode } from "react";
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
}

/**
 * Renders the restricted Markdown AST with React text nodes only: no dangerouslySetInnerHTML,
 * no links and no images from model text. [n] becomes a button only when citation n exists.
 */
function MarkdownImpl({ text, citations, onCite, citeLabel }: MarkdownProps) {
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
          <p key={`p-${i}`}>{renderInline(block.children, `p-${i}`)}</p>
        ) : (
          <ul key={`l-${i}`}>
            {block.items.map((item, j) => (
              <li key={`l-${i}-${j}`}>{renderInline(item, `l-${i}-${j}`)}</li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
