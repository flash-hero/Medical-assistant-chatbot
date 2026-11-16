import { useTranslations } from "next-intl";
import { Mark } from "@/components/brand/Mark";
import { Link } from "@/i18n/navigation";

export default function LocaleNotFound() {
  const t = useTranslations("NotFound");
  return (
    <main id="main" className="mx-auto grid min-h-[70dvh] max-w-md place-content-center gap-5 px-4 text-center">
      <Mark size={56} className="mx-auto text-brand" />
      <h1 className="text-3xl font-bold">{t("title")}</h1>
      <p className="text-ink-2">{t("body")}</p>
      <p>
        <Link href="/" className="btn btn-primary">
          {t("home")}
        </Link>
      </p>
    </main>
  );
}
