import { ListIcon } from "@phosphor-icons/react/dist/ssr/List";
import { getTranslations } from "next-intl/server";
import { Logo } from "@/components/brand/Logo";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";
import type { SitePath } from "@/lib/site";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

interface SiteHeaderProps {
  readonly locale: Locale;
  readonly path: SitePath;
}

export async function SiteHeader({ locale, path }: SiteHeaderProps) {
  const t = await getTranslations({ locale, namespace: "Common" });
  const names = { en: t("languages.en"), fr: t("languages.fr"), ar: t("languages.ar") };
  const themeLabels = { system: t("theme.system"), light: t("theme.light"), dark: t("theme.dark") };
  const links = [
    { href: "/#how", label: t("nav.how") },
    { href: "/sources", label: t("nav.sources"), current: path === "/sources" },
    { href: "/about", label: t("nav.about"), current: path === "/about" },
  ] as const;

  return (
    <header className="sticky top-0 z-[var(--z-header)] border-b border-line bg-bg">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4 sm:px-6">
        <Link href="/" className="me-auto rounded-full no-underline" aria-label={t("home")}>
          <Logo name={t("brand")} />
        </Link>
        <nav aria-label={t("menu")} className="hidden md:block">
          <ul className="flex items-center gap-1">
            {links.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={"current" in link && link.current ? "page" : undefined}
                  className="btn btn-ghost px-3 font-medium aria-[current=page]:text-brand"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <LanguageSwitcher locale={locale} path={path} label={t("languageLabel")} names={names} />
        <ThemeToggle labels={themeLabels} />
        <Link href="/chat" className="btn btn-primary hidden md:inline-flex">
          {t("askCta")}
        </Link>
        <button type="button" popoverTarget="site-menu" className="btn btn-ghost btn-icon md:hidden" aria-label={t("menu")}>
          <ListIcon size={24} aria-hidden="true" />
        </button>
        <div id="site-menu" popover="auto" className="popover-menu md:hidden" aria-label={t("menu")}>
          <ul className="grid gap-1 p-2">
            {links.map((link) => (
              <li key={link.href}>
                <Link href={link.href} className="flex min-h-11 items-center rounded-xl px-3 text-ink no-underline hover:bg-surface-2">
                  {link.label}
                </Link>
              </li>
            ))}
            <li className="pt-1">
              <Link href="/chat" className="btn btn-primary w-full">
                {t("askCta")}
              </Link>
            </li>
          </ul>
        </div>
      </div>
    </header>
  );
}
