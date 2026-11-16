"use client";

import { FirstAidIcon } from "@phosphor-icons/react/dist/ssr/FirstAid";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { useChatActions } from "./ChatContext";
import { ContactLink } from "./ContactLink";

/** "When to seek care": general guidance, the emergency number from the verified hospital profile only. */
export function SeekCarePanel() {
  const t = useTranslations("Chat");
  const { hospital } = useChatActions();
  const headingId = useId();
  const emergency = hospital?.emergency ?? null;
  return (
    <section aria-labelledby={headingId} className="grid gap-3 rounded-2xl border border-line bg-surface-2 p-4" data-testid="seek-care">
      <h3 id={headingId} className="flex items-center gap-2 font-bold">
        <FirstAidIcon size={22} aria-hidden="true" className="text-brand" />
        {t("seekCareTitle")}
      </h3>
      <ul className="grid list-disc gap-1 ps-5">
        <li>{emergency ? t("seekCareUrgent", { number: emergency.number }) : t("seekCareUrgentNoNumber")}</li>
        <li>{t("seekCareRoutine")}</li>
      </ul>
      {emergency ? (
        <div className="grid sm:w-fit">
          <ContactLink contact={{ ...emergency, label: emergency.label || t("emergencyLabel") }} callLabel={t("call", { label: emergency.label || t("emergencyLabel") })} tone="danger" />
        </div>
      ) : null}
      <p className="text-sm text-ink-2">{t("seekCareNote")}</p>
    </section>
  );
}
