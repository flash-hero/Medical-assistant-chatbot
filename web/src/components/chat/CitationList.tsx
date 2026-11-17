"use client";

import { useTranslations } from "next-intl";
import { directionOf } from "@/i18n/routing";
import type { ChatLocale, Citation } from "@/lib/chat/types";
import { useChatActions } from "./ChatContext";

function dirOf(language: string): "ltr" | "rtl" {
  return language === "ar" ? directionOf("ar") : "ltr";
}

/** Numbered source chips under an answer; each opens the source drawer. */
export function CitationList({ citations, answerLocale }: { readonly citations: readonly Citation[]; readonly answerLocale: ChatLocale }) {
  const t = useTranslations("Chat");
  const { openSource } = useChatActions();
  if (citations.length === 0) return null;
  return (
    <div className="grid gap-2">
      <h3 className="text-sm font-bold text-ink-2">{t("sourcesHeading")}</h3>
      <ul className="flex flex-wrap gap-2" data-testid="citations">
        {citations.map((citation) => (
          <li key={citation.n} className="max-w-full">
            <button
              type="button"
              className="flex min-h-11 max-w-full items-center gap-2 rounded-full border border-line bg-surface py-1.5 pe-4 ps-1.5 text-start text-sm transition-colors hover:border-brand"
              onClick={(e) => openSource(citation, answerLocale, e.currentTarget)}
              data-cite-chip={citation.n}
            >
              {/* Name from content (no aria-label) so it contains the visible text: "Source 1: <title>, <publisher>". */}
              <span className="cite-chip m-0 shrink-0" aria-hidden="true">
                {citation.n}
              </span>
              <span className="sr-only">{t("sourceNumber", { n: citation.n })} </span>
              <span className="grid min-w-0">
                <span className="truncate font-semibold" lang={citation.language} dir={dirOf(citation.language)}>
                  {citation.title}
                </span>
                <span className="sr-only">, </span>
                <span className="truncate text-xs text-ink-2" lang={citation.language} dir={dirOf(citation.language)}>
                  {citation.publisher}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
