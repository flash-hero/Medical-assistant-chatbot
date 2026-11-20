"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Mark } from "@/components/brand/Mark";
import { isLocale } from "@/i18n/routing";
import { telHref, type PhoneContact, type PublicHospital } from "@/lib/api/hospital";

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
 * Tap-to-call, like components/chat/ContactLink but without the icon module: this boundary ships with
 * every page, so it stays small. The name comes from the content and contains the visible text.
 */
function CallLink({ contact, callLabel, primary }: { readonly contact: PhoneContact; readonly callLabel: string; readonly primary: boolean }) {
  return (
    <a href={telHref(contact.number)} className={`btn ${primary ? "btn-danger" : "btn-quiet"} min-h-12 justify-start gap-3 whitespace-normal px-4 text-start`}>
      <span className="grid">
        <span className="sr-only">{callLabel}</span>
        <span aria-hidden="true">{contact.label}</span>
        <span className="sr-only">, </span>
        <span className="text-lg font-bold tabular-nums" dir="ltr">
          {contact.number}
        </span>
      </span>
    </a>
  );
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
    // Loaded only once an error is on screen: the API client stays out of every page's first-load
    // JavaScript (this boundary is part of the layout, so a static import is duplicated on each route).
    import("@/lib/api/client")
      .then(({ getHospital }) => getHospital(locale, controller.signal))
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
                <CallLink contact={contact} callLabel={t("call", { label: contact.label })} primary={i === 0} />
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
