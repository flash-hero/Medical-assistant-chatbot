"use client";

import { useTranslations } from "next-intl";
import { Mark } from "@/components/brand/Mark";
import { STAGES, type Stage } from "@/lib/chat/types";

/**
 * Calm progress while Ausculta works: the mark breathes, the current step is named, and the four
 * steps show how far along the turn is. Not a live region (the announcer handles speech).
 */
export function StatusLine({ stage }: { readonly stage: Stage | null }) {
  const t = useTranslations("Chat");
  const current = stage ?? "checking";
  const index = STAGES.indexOf(current);
  return (
    <div className="flex items-center gap-3 py-1 text-brand-ink" data-testid="status-line" data-stage={current}>
      <Mark size={24} small className="listening-ring shrink-0 text-brand" ringClassName="" />
      <span className="sr-only">{t("statusLabel")}: </span>
      <span className="relative grid min-h-6 flex-1 font-semibold">
        {/* Keyed: each new step mounts and rises in (CSS, opacity only under reduced motion). */}
        <span key={current} className="enter-step">
          {t(`status.${current}`)}
        </span>
      </span>
      <span className="flex gap-1" aria-hidden="true">
        {STAGES.map((s, i) => (
          <span key={s} className={`h-1.5 w-5 rounded-full ${i <= index ? "bg-brand" : "bg-line"}`} />
        ))}
      </span>
    </div>
  );
}
