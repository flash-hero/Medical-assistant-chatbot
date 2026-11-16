"use client";

import { useTranslations } from "next-intl";
import { Mark } from "@/components/brand/Mark";

const EXAMPLES = ["one", "two", "three", "four"] as const;

/** First screen of the chat: what Ausculta is for, and four example questions in the current language. */
export function EmptyState({ onPick, disabled }: { readonly onPick: (question: string) => void; readonly disabled: boolean }) {
  const t = useTranslations("Chat");
  return (
    <div className="grid gap-6 py-8 sm:py-14" data-testid="empty-state">
      <Mark size={56} className="text-brand" />
      <div className="grid gap-2">
        <h2 className="text-3xl font-bold sm:text-4xl">{t("emptyTitle")}</h2>
        <p className="max-w-[56ch] text-lg text-ink-2">{t("emptyBody")}</p>
      </div>
      <section aria-labelledby="examples-title" className="grid gap-3">
        <h3 id="examples-title" className="text-sm font-bold text-ink-2">
          {t("examplesLabel")}
        </h3>
        <ul className="grid gap-2 sm:grid-cols-2">
          {EXAMPLES.map((key) => (
            <li key={key} className="grid">
              <button
                type="button"
                disabled={disabled}
                onClick={() => onPick(t(`examples.${key}`))}
                className="min-h-14 rounded-2xl border border-line bg-surface px-4 py-3 text-start transition-colors hover:border-brand hover:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-60"
                data-testid="example-question"
              >
                {t(`examples.${key}`)}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
