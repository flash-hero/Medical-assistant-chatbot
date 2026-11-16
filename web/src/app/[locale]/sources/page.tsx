import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/ssr/ArrowSquareOut";
import type { Metadata } from "next";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import attributionData from "@/content/attribution.json";
import { routing, type Locale } from "@/i18n/routing";
import { parseAttribution, type AttributionSource } from "@/lib/attribution";
import { alternatesFor } from "@/lib/site";

interface PageProps {
  readonly params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "Meta" });
  return { title: t("sourcesTitle"), alternates: alternatesFor(locale, "/sources") };
}

function formatDate(locale: Locale, iso: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
}

async function SourceEntry({ locale, source }: { readonly locale: Locale; readonly source: AttributionSource }) {
  const t = await getTranslations({ locale, namespace: "Sources" });
  const common = await getTranslations({ locale, namespace: "Common" });
  const languageNames = new Intl.DisplayNames([locale], { type: "language" });
  return (
    <article className="grid gap-5 rounded-card border border-line bg-surface p-6 sm:p-8" aria-labelledby={`src-${source.id}`}>
      <header className="grid gap-1">
        <h2 id={`src-${source.id}`} className="text-2xl font-bold" lang="en" dir="ltr">
          {source.name}
        </h2>
        <p className="text-ink-2" lang="en" dir="ltr">
          {source.publisher}
        </p>
      </header>
      <dl className="grid gap-4 sm:grid-cols-[12rem_1fr]">
        <dt className="font-semibold">{t("licence")}</dt>
        <dd lang="en" dir="ltr">{source.license.name}</dd>
        <dt className="font-semibold">{t("attribution")}</dt>
        <dd lang="en" dir="ltr">{source.license.attribution}</dd>
        <dt className="font-semibold">{t("languages")}</dt>
        <dd>{source.languages.map((l) => languageNames.of(l) ?? l).join(", ")}</dd>
        {source.license.conditions.length > 0 ? (
          <>
            <dt className="font-semibold">{t("conditions")}</dt>
            <dd>
              <ul className="grid list-disc gap-1.5 ps-5" lang="en" dir="ltr">
                {source.license.conditions.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
      {source.license.verifiedOn ? (
        <p className="text-sm text-ink-2">{t("verified", { date: formatDate(locale, source.license.verifiedOn) })}</p>
      ) : null}
      <p className="flex flex-wrap gap-3">
        <a className="btn btn-quiet" href={source.license.evidenceUrl} target="_blank" rel="noopener noreferrer">
          {t("terms")}
          <ArrowSquareOutIcon size={18} aria-hidden="true" />
          <span className="sr-only">{common("newTab")}</span>
        </a>
        <a className="btn btn-quiet" href={source.homepage} target="_blank" rel="noopener noreferrer">
          {t("homepage", { name: source.name })}
          <ArrowSquareOutIcon size={18} aria-hidden="true" />
          <span className="sr-only">{common("newTab")}</span>
        </a>
      </p>
    </article>
  );
}

export default async function SourcesPage({ params }: PageProps) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "Sources" });
  const { sources, generatedOn } = parseAttribution(attributionData);
  return (
    <>
      <SiteHeader locale={locale} path="/sources" />
      <main id="main" tabIndex={-1} className="mx-auto grid max-w-4xl gap-10 px-4 pt-12 outline-none sm:px-6 md:pt-16">
        <header className="grid max-w-[62ch] gap-4">
          <h1 className="text-4xl font-bold sm:text-5xl">{t("title")}</h1>
          <p className="text-lg text-ink-2">{t("intro")}</p>
          <p className="text-ink-2">{t("noEndorsement")}</p>
        </header>
        {sources.length === 0 ? <p>{t("empty")}</p> : null}
        {sources.map((source) => (
          <SourceEntry key={source.id} locale={locale} source={source} />
        ))}
        {generatedOn ? <p className="text-sm text-ink-2">{t("generated", { date: formatDate(locale, generatedOn) })}</p> : null}
      </main>
      <SiteFooter locale={locale} />
    </>
  );
}
