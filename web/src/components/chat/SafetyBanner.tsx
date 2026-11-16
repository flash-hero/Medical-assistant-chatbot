"use client";

import { WarningIcon } from "@phosphor-icons/react/dist/ssr/Warning";
import { AnimatePresence, m } from "motion/react";
import { useTranslations } from "next-intl";
import type { SafetyEvent } from "@/lib/chat/types";
import { ContactLink } from "./ContactLink";

/**
 * Emergency / crisis banner. Sticky under the header for the rest of the session, shown before any
 * answer text, with tap-to-call links built only from the event's verified contacts.
 */
export function SafetyBanner({ safety }: { readonly safety: SafetyEvent | null }) {
  const t = useTranslations("Chat");
  return (
    <AnimatePresence initial={false}>
      {safety ? (
        <m.section
          key={safety.template_id}
          role="alert"
          aria-labelledby="safety-title"
          data-testid="safety-banner"
          data-kind={safety.kind}
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.25, 1, 0.5, 1] }}
          className="sticky top-16 z-[var(--z-sticky)] border-b border-danger-line bg-danger-soft text-danger-ink"
        >
          <div className="mx-auto grid max-w-3xl gap-3 px-4 py-4 sm:px-6">
            <h2 id="safety-title" className="flex items-center gap-2 text-lg font-bold">
              <WarningIcon size={26} weight="fill" aria-hidden="true" className="shrink-0 text-danger" />
              {safety.title}
            </h2>
            <p className="max-w-[68ch]">{safety.message}</p>
            {safety.contacts.length > 0 ? (
              <ul className="grid gap-2 sm:grid-cols-2" aria-label={t("safetyContacts")}>
                {safety.contacts.map((contact, i) => (
                  <li key={`${contact.number}-${i}`} className="grid">
                    <ContactLink contact={contact} callLabel={t("call", { label: contact.label })} tone={i === 0 ? "danger" : "quiet"} />
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </m.section>
      ) : null}
    </AnimatePresence>
  );
}
