import { EarIcon, MagnifyingGlassIcon, QuotesIcon, ShieldCheckIcon } from "@/components/ui/icons";
import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { PreviewAnswer, type PreviewCopy } from "./PreviewAnswer";

const STEPS = [
  { key: "listen", Icon: EarIcon },
  { key: "check", Icon: ShieldCheckIcon },
  { key: "search", Icon: MagnifyingGlassIcon },
  { key: "answer", Icon: QuotesIcon },
] as const;

/**
 * Signature moment: the steps scroll past a sticky (CSS, no pin, no CLS) preview that advances
 * from question to cited answer. Without JS or with reduced motion, every step shows the final state.
 */
export async function HowItWorks({ locale, copy }: { readonly locale: Locale; readonly copy: PreviewCopy }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  return (
    <section id="how" aria-labelledby="how-title" className="border-y border-line bg-surface-2">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 lg:py-28">
        <div className="grid max-w-[40rem] gap-3" data-reveal>
          <h2 id="how-title" className="text-3xl font-bold sm:text-4xl">
            {t("howTitle")}
          </h2>
          <p className="text-lg text-ink-2">{t("howIntro")}</p>
        </div>
        <div className="mt-12 grid gap-10 lg:grid-cols-[1fr_1.05fr] lg:gap-16" data-how>
          <div className="relative">
            <span aria-hidden="true" className="absolute inset-y-2 start-[1.375rem] w-px bg-line" />
            <span aria-hidden="true" className="how-progress absolute inset-y-2 start-[1.375rem] w-px bg-brand" />
            <ol className="relative grid gap-10 lg:gap-0">
              {STEPS.map(({ key, Icon }, i) => (
                <li key={key} className="how-step grid grid-cols-[2.75rem_1fr] gap-4 lg:min-h-[42vh]" data-step={i + 1} data-active="">
                  <span className="how-dot grid size-11 place-items-center rounded-full border border-line bg-surface text-brand">
                    <Icon size={22} aria-hidden="true" />
                  </span>
                  <div className="grid content-start gap-2 pt-1.5">
                    <h3 className="text-xl font-bold">
                      <span className="sr-only">{i + 1}. </span>
                      {t(`steps.${key}.title`)}
                    </h3>
                    <p className="max-w-[46ch] text-ink-2">{t(`steps.${key}.body`)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className="hidden lg:block">
            <div className="sticky top-28" aria-hidden="true">
              <PreviewAnswer copy={copy} staged />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
