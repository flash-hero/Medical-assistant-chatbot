"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";
import { WarningIcon } from "@/components/ui/icons";
import type { PublicHospital } from "@/lib/api/hospital";
import { safetyLanguage } from "@/lib/chat/language";
import { safetyContacts } from "@/lib/chat/safety";
import type { SafetyEvent } from "@/lib/chat/types";
import { dirOf } from "@/lib/i18n/text-language";
import { ContactLink } from "./ContactLink";

/**
 * One safety message. Its title and message are in the event's own language and direction (review T1);
 * an event that arrived without them (contract drift) shows the localised fallback (review T4).
 */
function SafetyMessage({ event, titleId }: { readonly event: SafetyEvent; readonly titleId: string | undefined }) {
  const t = useTranslations("Chat");
  const language = safetyLanguage(event) ?? undefined;
  const title = event.title || t("safetyFallback.title");
  const message = event.message || t("safetyFallback.message");
  return (
    <div className="grid gap-2" data-safety-kind={event.kind}>
      <h2 id={titleId} className="flex items-center gap-2 text-lg font-bold" lang={event.title ? language : undefined} dir={dirOf(title)}>
        <WarningIcon size={26} weight="fill" aria-hidden="true" className="shrink-0 text-danger" />
        {title}
      </h2>
      <p className="max-w-[68ch]" lang={event.message ? language : undefined} dir={dirOf(message)}>
        {message}
      </p>
    </div>
  );
}

interface SafetyBodyProps {
  readonly events: readonly SafetyEvent[];
  readonly hospital: PublicHospital | null;
  readonly titleId: string;
}

/**
 * Every safety message, highest priority first, then one merged list of tap-to-call contacts built
 * only from verified numbers (the events', else the hospital profile's).
 */
export function SafetyBody({ events, hospital, titleId }: SafetyBodyProps) {
  const t = useTranslations("Chat");
  const contacts = safetyContacts(events, hospital);
  return (
    <div className="grid gap-4">
      {events.map((event, i) => (
        <SafetyMessage key={event.kind} event={event} titleId={i === 0 ? titleId : undefined} />
      ))}
      {contacts.length > 0 ? (
        <ul className="grid gap-2 sm:grid-cols-2" aria-label={t("safetyContacts")}>
          {contacts.map((contact, i) => (
            <li key={`${i}-${contact.number}`} className="grid">
              <ContactLink contact={contact} callLabel={t("call", { label: contact.label })} tone={i === 0 ? "danger" : "quiet"} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="font-semibold">{t("safetyFallback.noNumber")}</p>
      )}
    </div>
  );
}

interface SafetyBannerProps {
  readonly safety: readonly SafetyEvent[];
  readonly hospital: PublicHospital | null;
}

/**
 * Emergency / crisis banner. Sticky under the header for the rest of the session, shown before any
 * answer text. Several kinds in one session are all kept, highest priority first (review T2). It drops
 * in once (CSS `enter-drop`; instant under reduced motion).
 */
export function SafetyBanner({ safety, hospital }: SafetyBannerProps) {
  const titleId = useId();
  const first = safety[0];
  if (!first) return null;
  return (
    <section
      role="alert"
      aria-labelledby={titleId}
      data-testid="safety-banner"
      data-kind={first.kind}
      className="enter-drop sticky top-16 z-[var(--z-sticky)] border-b border-danger-line bg-danger-soft text-danger-ink"
    >
      <div className="mx-auto max-w-3xl px-4 py-4 sm:px-6">
        <SafetyBody events={safety} hospital={hospital} titleId={titleId} />
      </div>
    </section>
  );
}
