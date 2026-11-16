import { getTranslations } from "next-intl/server";
import { Mark } from "@/components/brand/Mark";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";

/** Intended-purpose disclaimer, demo status and the attribution link appear on every page. */
export async function SiteFooter({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Footer" });
  const common = await getTranslations({ locale, namespace: "Common" });
  return (
    <footer className="mt-24 border-t border-line bg-surface-2">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_1fr]">
        <section aria-labelledby="footer-purpose" className="grid max-w-[62ch] content-start gap-3">
          <h2 id="footer-purpose" className="text-base font-bold">
            {t("disclaimerTitle")}
          </h2>
          <p className="text-ink-2">{t("disclaimer")}</p>
          <p className="w-fit rounded-full border border-warn-line bg-warn-soft px-3 py-1 text-sm font-semibold text-warn-ink">
            {t("demo")}
          </p>
          <p className="text-sm text-ink-2">
            {t("attribution")}{" "}
            <Link href="/sources" className="font-semibold text-brand underline underline-offset-4">
              {t("sourcesLink")}
            </Link>
          </p>
        </section>
        <nav aria-labelledby="footer-links" className="grid content-start gap-3">
          <h2 id="footer-links" className="flex items-center gap-2 text-base font-bold">
            <Mark size={20} small className="text-brand" />
            {common("brand")}
          </h2>
          <ul className="grid gap-1">
            <li>
              <Link href="/chat" className="inline-flex min-h-11 items-center text-ink underline-offset-4 hover:underline">
                {t("chatLink")}
              </Link>
            </li>
            <li>
              <Link href="/sources" className="inline-flex min-h-11 items-center text-ink underline-offset-4 hover:underline">
                {t("sourcesLink")}
              </Link>
            </li>
            <li>
              <Link href="/about" className="inline-flex min-h-11 items-center text-ink underline-offset-4 hover:underline">
                {t("aboutLink")}
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
