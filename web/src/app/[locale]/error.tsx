"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Mark } from "@/components/brand/Mark";
import { ContactLink } from "@/components/chat/ContactLink";
import { isLocale } from "@/i18n/routing";
import { getHospital, type PublicHospital } from "@/lib/api/client";
import type { PhoneContact } from "@/lib/api/hospital";

interface LocaleErrorProps {
  readonly error: Error & { readonly digest?: string };
  /** Re-fetches and re-renders the segment (Next 16.3+; preferred over `reset`). */
  readonly retry: () => void;
}

function emergencyContacts(hospital: PublicHospital | null, emergencyLabel: string): readonly PhoneContact[] {
  if (!hospital) return [];
  const emergency = hospital.emergency ? [{ ...hospital.emergency, label: hospital.emergency.label || emergencyLabel }] : [];
  const handoff = hospital.handoff ? [hospital.handoff] : [];
  return [...emergency, ...hospital.crisisLines, ...handoff];
}

/**
 * Error boundary for every page of a locale (review T11). A rendering error must never leave a patient
 * on a blank screen: the page says what happened in their language and keeps the emergency numbers
 * one tap away (from the verified hospital profile, else a generic instruction). The home link is a
 * plain link on purpose: a full page load starts again from a clean state.
 */
export default function LocaleError({ retry }: LocaleErrorProps) {
  const t = useTranslations("ErrorPage");
  const raw = useLocale();
  const locale = isLocale(raw) ? raw : "en";
  const [hospital, setHospital] = useState<PublicHospital | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHospital(locale, controller.signal)
      .then(setHospital)
      .catch(() => undefined); // the generic emergency instruction stays
    return () => controller.abort();
  }, [locale]);

  const contacts = emergencyContacts(hospital, t("emergencyLabel"));
  return (
    <main id="main" tabIndex={-1} className="mx-auto grid min-h-[70dvh] max-w-md content-center gap-5 px-4 py-12 outline-none" data-testid="error-page">
      <Mark size={56} className="text-brand" />
      <h1 className="text-3xl font-bold">{t("title")}</h1>
      <p className="text-ink-2">{t("body")}</p>
      {contacts.length > 0 ? (
        <section className="grid gap-2" aria-labelledby="error-emergency">
          <h2 id="error-emergency" className="font-semibold">
            {t("emergency")}
          </h2>
          <ul className="grid gap-2">
            {contacts.map((contact, i) => (
              <li key={`${i}-${contact.number}`} className="grid">
                <ContactLink contact={contact} callLabel={t("call", { label: contact.label })} tone={i === 0 ? "danger" : "quiet"} />
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <p className="font-semibold">{t("emergencyNoNumber")}</p>
      )}
      <p className="flex flex-wrap gap-3">
        <button type="button" className="btn btn-primary" onClick={() => retry()}>
          {t("retry")}
        </button>
        <a href={`/${locale}`} className="btn btn-quiet">
          {t("home")}
        </a>
      </p>
    </main>
  );
}
