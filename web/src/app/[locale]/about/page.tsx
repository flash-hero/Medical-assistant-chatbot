import { CheckCircleIcon, ProhibitIcon } from "@/components/ui/icons";
import type { Metadata } from "next";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { alternatesFor } from "@/lib/site";

interface PageProps {
  readonly params: Promise<{ locale: string }>;
}

const IS = ["explain", "navigate", "care"] as const;
const IS_NOT = ["diagnosis", "triage", "prescriber", "clinician", "emergency"] as const;
const NOTES = ["why", "privacy", "demo", "contact"] as const;

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "Meta" });
  return { title: t("aboutTitle"), alternates: alternatesFor(locale, "/about") };
}

export default async function AboutPage({ params }: PageProps) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "About" });
  const common = await getTranslations({ locale, namespace: "Common" });
  return (
    <>
      <SiteHeader locale={locale} path="/about" />
      <main id="main" tabIndex={-1} className="mx-auto grid max-w-4xl gap-14 px-4 pt-12 outline-none sm:px-6 md:pt-16">
        <header className="grid max-w-[62ch] gap-4">
          <h1 className="text-4xl font-bold sm:text-5xl">{t("title")}</h1>
          <p className="text-xl text-ink-2">{t("lead")}</p>
        </header>
        <section aria-labelledby="about-is" className="grid gap-5">
          <h2 id="about-is" className="text-2xl font-bold">
            {t("isTitle")}
          </h2>
          <ul className="grid gap-4">
            {IS.map((key) => (
              <li key={key} className="grid max-w-[68ch] grid-cols-[1.5rem_1fr] gap-3">
                <CheckCircleIcon size={24} weight="fill" aria-hidden="true" className="text-brand" />
                <span>{t(`is.${key}`)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="about-is-not" className="grid gap-5 rounded-card border border-line bg-surface p-6 sm:p-8">
          <h2 id="about-is-not" className="text-2xl font-bold">
            {t("isNotTitle")}
          </h2>
          <ul className="grid gap-4">
            {IS_NOT.map((key) => (
              <li key={key} className="grid max-w-[68ch] grid-cols-[1.5rem_1fr] gap-3">
                <ProhibitIcon size={24} aria-hidden="true" className="text-ink-2" />
                <span>{t(`isNot.${key}`)}</span>
              </li>
            ))}
          </ul>
        </section>
        <div className="grid gap-10 md:grid-cols-2">
          {NOTES.map((key) => (
            <section key={key} aria-labelledby={`about-${key}`} className="grid content-start gap-2">
              <h2 id={`about-${key}`} className="text-xl font-bold">
                {t(`${key}Title`)}
              </h2>
              <p className="text-ink-2">{t(key)}</p>
            </section>
          ))}
        </div>
        <p>
          <Link href="/chat" className="btn btn-primary px-6">
            {common("askCta")}
          </Link>
        </p>
      </main>
      <SiteFooter locale={locale} />
    </>
  );
}
