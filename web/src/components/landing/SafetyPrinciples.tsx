import { CheckCircleIcon, ProhibitIcon } from "@/components/ui/icons";
import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";

const NEVER = ["diagnose", "triage", "dose", "replace", "emergency"] as const;
const ALWAYS = ["cite", "seekCare", "human", "unknown", "label"] as const;

/** Two contrasting lists, the intended purpose made concrete. */
export async function SafetyPrinciples({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  return (
    <section aria-labelledby="safety-title" className="mx-auto max-w-6xl px-4 py-20 sm:px-6 lg:py-28">
      <div className="grid max-w-[44rem] gap-3" data-reveal>
        <h2 id="safety-title" className="text-3xl font-bold sm:text-4xl">
          {t("safetyTitle")}
        </h2>
        <p className="text-lg text-ink-2">{t("safetyIntro")}</p>
      </div>
      <div className="mt-12 grid gap-6 md:grid-cols-2">
        <div className="grid content-start gap-5 rounded-card border border-line bg-surface p-6 sm:p-8" data-reveal>
          <h3 className="text-xl font-bold">{t("neverTitle")}</h3>
          <ul className="grid gap-4">
            {NEVER.map((key) => (
              <li key={key} className="grid grid-cols-[1.5rem_1fr] gap-3">
                <ProhibitIcon size={24} aria-hidden="true" className="text-ink-2" />
                <span>{t(`never.${key}`)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="grid content-start gap-5 rounded-card bg-brand-soft p-6 text-brand-ink sm:p-8" data-reveal>
          <h3 className="text-xl font-bold">{t("alwaysTitle")}</h3>
          <ul className="grid gap-4">
            {ALWAYS.map((key) => (
              <li key={key} className="grid grid-cols-[1.5rem_1fr] gap-3">
                <CheckCircleIcon size={24} weight="fill" aria-hidden="true" />
                <span>{t(`always.${key}`)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
