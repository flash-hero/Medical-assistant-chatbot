import { ArrowDownIcon, ChatCircleIcon } from "@/components/ui/icons";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";
import { PreviewAnswer, type PreviewCopy } from "./PreviewAnswer";

/** Asymmetric split: the promise on one side, a real rendering of a cited answer on the other. */
export async function Hero({ locale, copy }: { readonly locale: Locale; readonly copy: PreviewCopy }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  const common = await getTranslations({ locale, namespace: "Common" });
  return (
    <section aria-labelledby="hero-title" className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6 md:pt-16 lg:pb-24">
      <div className="grid items-center gap-10 lg:grid-cols-[1.1fr_1fr] lg:gap-14">
        <div className="grid max-w-[36rem] gap-6">
          <h1 id="hero-title" className="text-[2.25rem] font-bold tracking-[-0.02em] sm:text-5xl lg:text-[3.5rem]">
            {t("heroTitle")}
          </h1>
          <p className="max-w-[46ch] text-lg text-ink-2 sm:text-xl">{t("heroSubtitle")}</p>
          <div className="flex flex-wrap gap-3">
            <Link href="/chat" className="btn btn-primary px-6 text-lg">
              <ChatCircleIcon size={22} aria-hidden="true" />
              {common("askCta")}
            </Link>
            <a href="#how" className="btn btn-quiet px-6 text-lg">
              {t("heroSecondary")}
              <ArrowDownIcon size={20} aria-hidden="true" />
            </a>
          </div>
        </div>
        <figure className="hero-rise grid gap-3" aria-label={t("previewLabel")}>
          <PreviewAnswer copy={copy} />
          <figcaption className="text-sm text-ink-2">{t("previewCaption")}</figcaption>
        </figure>
      </div>
    </section>
  );
}
