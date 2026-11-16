import { PlusIcon } from "@phosphor-icons/react/dist/ssr/Plus";
import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";

const QUESTIONS = ["doctor", "sources", "privacy", "emergency", "languages", "unknown"] as const;

/** Native disclosure widgets: keyboard and screen-reader support without JavaScript. */
export async function Faq({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  return (
    <section aria-labelledby="faq-title" className="mx-auto max-w-6xl px-4 pb-8 pt-12 sm:px-6">
      <div className="grid gap-10 lg:grid-cols-[1fr_1.6fr]">
        <h2 id="faq-title" className="text-3xl font-bold sm:text-4xl lg:sticky lg:top-28 lg:self-start" data-reveal>
          {t("faqTitle")}
        </h2>
        <div className="grid divide-y divide-line border-y border-line">
          {QUESTIONS.map((key) => (
            <details key={key} className="faq group">
              <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-4 text-lg font-bold [&::-webkit-details-marker]:hidden">
                {t(`faq.${key}.q`)}
                <PlusIcon
                  size={22}
                  aria-hidden="true"
                  className="shrink-0 text-brand transition-transform duration-200 group-open:rotate-45"
                />
              </summary>
              <p className="max-w-[62ch] pb-5 text-ink-2">{t(`faq.${key}.a`)}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
