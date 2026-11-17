"use client";

import { ArrowSquareOutIcon, XIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import type { ChatLocale, Citation } from "@/lib/chat/types";

export interface OpenSource {
  readonly citation: Citation;
  /** The language the answer citing this source is written in (not necessarily the UI locale). */
  readonly answerLanguage: ChatLocale;
}

interface SourceDrawerProps {
  readonly source: OpenSource | null;
  /** The UI locale: the drawer's own labels and the review date are in it. */
  readonly uiLocale: ChatLocale;
  readonly onClose: () => void;
}

/** A localised date, or null for a value no calendar knows: a bad date must never crash the chat (review T11). */
function formatReviewed(locale: ChatLocale, iso: string): string | null {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(date);
}

/**
 * Native modal <dialog> (focus trap, Escape, inert page). The only external links in the chat live
 * here, built from server-side citations (already validated as http/https), never from model text.
 */
export function SourceDrawer({ source, uiLocale, onClose }: SourceDrawerProps) {
  const t = useTranslations("Chat");
  const common = useTranslations("Common");
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (source && !dialog.open) dialog.showModal();
    if (!source && dialog.open) dialog.close();
  }, [source]);

  const citation = source?.citation;
  const dir = citation?.language === "ar" ? "rtl" : "ltr";
  const reviewed = citation?.reviewed_on ? formatReviewed(uiLocale, citation.reviewed_on) : null;
  return (
    <dialog ref={ref} className="drawer" aria-labelledby="source-drawer-title" onClose={onClose} data-testid="source-drawer">
      {citation && source ? (
        <div className="grid h-full content-start gap-5 overflow-y-auto p-6">
          <div className="flex items-start justify-between gap-4">
            <p id="source-drawer-title" className="flex items-center gap-2 text-lg font-bold">
              <span className="cite-chip m-0" aria-hidden="true">
                {citation.n}
              </span>
              {t("drawer.title", { n: citation.n })}
            </p>
            <button type="button" className="btn btn-ghost btn-icon -me-2 -mt-1" onClick={() => ref.current?.close()} aria-label={t("drawer.close")} autoFocus>
              <XIcon size={22} aria-hidden="true" />
            </button>
          </div>
          <h2 className="text-2xl font-bold" lang={citation.language} dir={dir} data-testid="source-title">
            {citation.title}
          </h2>
          <dl className="grid gap-3">
            <div className="grid gap-0.5">
              <dt className="text-sm font-semibold text-ink-2">{t("drawer.publisher")}</dt>
              <dd lang={citation.language} dir={dir}>{citation.publisher}</dd>
            </div>
            {citation.heading ? (
              <div className="grid gap-0.5">
                <dt className="text-sm font-semibold text-ink-2">{t("drawer.section")}</dt>
                <dd lang={citation.language} dir={dir}>{citation.heading}</dd>
              </div>
            ) : null}
          </dl>
          {reviewed ? <p className="text-sm text-ink-2">{t("drawer.reviewed", { date: reviewed })}</p> : null}
          {citation.language !== source.answerLanguage ? (
            <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm" data-testid="source-language-note">
              {t("drawer.languageNote", { language: t(`languageNames.${citation.language}`) })}
            </p>
          ) : null}
          {citation.snippet ? (
            <figure className="grid gap-2">
              <figcaption className="text-sm font-semibold text-ink-2">{t("drawer.excerpt")}</figcaption>
              <blockquote className="rounded-xl bg-surface-2 p-4" lang={citation.language} dir={dir} data-testid="source-snippet">
                {citation.snippet}
              </blockquote>
            </figure>
          ) : null}
          <a href={citation.url} target="_blank" rel="noopener noreferrer" className="btn btn-primary w-fit" data-testid="source-link">
            {t("drawer.open")}
            <ArrowSquareOutIcon size={20} aria-hidden="true" />
            <span className="sr-only">{common("newTab")}</span>
          </a>
        </div>
      ) : null}
    </dialog>
  );
}
