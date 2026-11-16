import { MagnifyingGlassIcon, SealCheckIcon, ShieldCheckIcon } from "@/components/ui/icons";
import type { ReactNode } from "react";
import { Mark } from "@/components/brand/Mark";
import { parseMarkdown, type Inline } from "@/lib/markdown/parse";

export interface PreviewCopy {
  readonly you: string;
  readonly assistant: string;
  readonly question: string;
  readonly answer: string;
  readonly verified: string;
  readonly sourcesHeading: string;
  readonly sourceTitle: string;
  readonly sourcePublisher: string;
  readonly sourceSnippet: string;
  readonly checking: string;
  readonly searching: string;
}

/** Static rendering of the answer AST: the citation marker is a visual chip here, not a control. */
function renderInline(nodes: readonly Inline[], key: string): ReactNode[] {
  return nodes.map((node, i) => {
    if (node.type === "text") return node.value;
    if (node.type === "strong") return <strong key={`${key}-${i}`}>{renderInline(node.children, `${key}-${i}`)}</strong>;
    return (
      <span key={`${key}-${i}`} className="cite-chip pointer-events-none" aria-hidden="true">
        {node.n}
      </span>
    );
  });
}

function AnswerBody({ text }: { readonly text: string }) {
  return (
    <div className="prose-answer">
      {parseMarkdown(text).map((block, i) =>
        block.type === "paragraph" ? (
          <p key={i}>{renderInline(block.children, `p${i}`)}</p>
        ) : (
          <ul key={i}>
            {block.items.map((item, j) => (
              <li key={j}>{renderInline(item, `l${i}-${j}`)}</li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

function StatusRow({ icon, label, stage }: { readonly icon: ReactNode; readonly label: string; readonly stage: string }) {
  return (
    <p data-only={stage} className="stage-layer flex items-center gap-2 text-sm font-semibold text-brand-ink">
      <Mark size={20} small className="listening-ring text-brand" />
      {icon}
      {label}
    </p>
  );
}

interface PreviewAnswerProps {
  readonly copy: PreviewCopy;
  /** Staged previews reveal one layer per "How it works" step; data-stage defaults to the final state. */
  readonly staged?: boolean;
  readonly className?: string;
}

export function PreviewAnswer({ copy, staged = false, className = "" }: PreviewAnswerProps) {
  return (
    <div
      className={`stage-host grid gap-4 rounded-card border border-line bg-surface p-5 shadow-[0_24px_60px_-36px_oklch(0.3_0.05_165/0.45)] sm:p-6 ${className}`}
      data-stage={staged ? "4" : undefined}
    >
      <div className="ms-auto max-w-[85%] rounded-[1.25rem] rounded-ee-md bg-brand-soft px-4 py-3 text-brand-ink">
        <span className="sr-only">{copy.you}: </span>
        {copy.question}
      </div>
      {/* Status rows and the answer share one grid cell, so switching stages never shifts the layout. */}
      <div className="grid [&>*]:[grid-area:1/1]">
        {staged ? (
          <>
            <StatusRow stage="2" label={copy.checking} icon={<ShieldCheckIcon size={18} aria-hidden="true" />} />
            <StatusRow stage="3" label={copy.searching} icon={<MagnifyingGlassIcon size={18} aria-hidden="true" />} />
          </>
        ) : null}
        <AnswerLayer copy={copy} />
      </div>
      <SourceLayer copy={copy} />
    </div>
  );
}

function AnswerLayer({ copy }: { readonly copy: PreviewCopy }) {
  return (
    <div data-from="4" className="stage-layer grid content-start gap-3">
        <p className="flex items-center gap-2 text-sm font-bold text-ink">
          <Mark size={22} small className="text-brand" />
          {copy.assistant}
        </p>
        <AnswerBody text={copy.answer} />
        <p className="flex items-center gap-1.5 text-sm font-semibold text-brand-ink">
          <SealCheckIcon size={18} aria-hidden="true" />
          {copy.verified}
        </p>
    </div>
  );
}

function SourceLayer({ copy }: { readonly copy: PreviewCopy }) {
  return (
      <figure data-from="3" className="stage-layer grid gap-1 rounded-2xl border border-line bg-surface-2 p-4 text-sm">
        <figcaption className="flex items-center gap-2 font-bold">
          <span className="cite-chip pointer-events-none" aria-hidden="true">
            1
          </span>
          <span lang="en" dir="ltr">
            {copy.sourceTitle}
          </span>
        </figcaption>
        <p className="text-ink-2" lang="en" dir="ltr">
          {copy.sourcePublisher}
        </p>
        <blockquote className="text-ink-2" lang="en" dir="ltr">
          {copy.sourceSnippet}
        </blockquote>
      </figure>
  );
}
