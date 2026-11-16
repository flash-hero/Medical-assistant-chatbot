import { ArrowRightIcon } from "@phosphor-icons/react/dist/ssr/ArrowRight";
import { BookOpenTextIcon } from "@phosphor-icons/react/dist/ssr/BookOpenText";
import { getTranslations } from "next-intl/server";
import attributionData from "@/content/attribution.json";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";
import { parseAttribution } from "@/lib/attribution";

/** An editorial statement followed by the publishers actually in the library, read from the registry export. */
export async function SourcesTrust({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  const { sources } = parseAttribution(attributionData);
  return (
    <section aria-labelledby="sources-title" className="bg-brand-soft text-brand-ink">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1.2fr_1fr] lg:py-24">
        <div className="grid content-start gap-5" data-reveal>
          <BookOpenTextIcon size={36} aria-hidden="true" />
          <h2 id="sources-title" className="text-3xl font-bold sm:text-4xl">
            {t("sourcesTitle")}
          </h2>
          <p className="max-w-[52ch] text-lg">{t("sourcesBody")}</p>
          <Link href="/sources" className="btn btn-primary w-fit px-6">
            {t("sourcesLink")}
            <ArrowRightIcon size={20} aria-hidden="true" className="rtl:-scale-x-100" />
          </Link>
        </div>
        <ul className="grid content-start gap-4" data-reveal>
          {sources.map((source) => (
            <li key={source.id} className="grid gap-1 rounded-card bg-surface p-5 text-ink">
              <p className="text-lg font-bold" lang="en" dir="ltr">
                {source.name}
              </p>
              <p className="text-ink-2" lang="en" dir="ltr">
                {source.publisher}
              </p>
              <p className="text-sm text-ink-2">
                {t("sourcesLicence", { licence: source.license.name })}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
