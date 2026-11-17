import { CheckIcon, TranslateIcon } from "@/components/ui/icons";
import { LOCALES, directionOf, type Locale } from "@/i18n/routing";
import type { SitePath } from "@/lib/site";

interface LanguageSwitcherProps {
  readonly locale: Locale;
  readonly path: SitePath;
  readonly label: string;
  readonly names: Readonly<Record<Locale, string>>;
  readonly id?: string;
}

/**
 * Native popover menu (light dismiss, Escape, top layer) with plain links: switching language is a full
 * navigation, because direction, fonts and the chat session all change with it.
 */
export function LanguageSwitcher({ locale, path, label, names, id = "language-menu" }: LanguageSwitcherProps) {
  const suffix = path === "/" ? "" : path;
  return (
    <div className="relative">
      <button
        type="button"
        popoverTarget={id}
        className="btn btn-ghost min-w-11 gap-1.5 px-3"
        aria-label={`${label}: ${names[locale]}`}
      >
        <TranslateIcon size={22} aria-hidden="true" />
        <span className="hidden text-sm sm:inline" lang={locale}>
          {names[locale]}
        </span>
      </button>
      <div id={id} popover="auto" className="popover-menu" aria-label={label}>
        <ul className="grid gap-1 p-1.5">
          {LOCALES.map((l) => (
            <li key={l}>
              <a
                href={`/${l}${suffix}`}
                hrefLang={l}
                lang={l}
                dir={directionOf(l)}
                aria-current={l === locale ? "true" : undefined}
                className="flex min-h-11 items-center justify-between gap-6 rounded-xl px-3 py-2 text-ink no-underline hover:bg-surface-2"
              >
                <span>{names[l]}</span>
                {l === locale ? <CheckIcon size={18} aria-hidden="true" className="text-brand" /> : null}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
