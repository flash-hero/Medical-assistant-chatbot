"use client";

import { HeadsetIcon } from "@phosphor-icons/react/dist/ssr/Headset";
import { NotePencilIcon } from "@phosphor-icons/react/dist/ssr/NotePencil";
import { useTranslations } from "next-intl";
import { Mark } from "@/components/brand/Mark";
import { LanguageSwitcher } from "@/components/site/LanguageSwitcher";
import { ThemeToggle } from "@/components/site/ThemeToggle";
import { Link } from "@/i18n/navigation";
import type { ChatLocale } from "@/lib/chat/types";

interface ChatHeaderProps {
  readonly locale: ChatLocale;
  readonly onHandoff: (trigger: HTMLElement) => void;
  readonly onNewConversation: () => void;
}

/** Chat chrome: the persistent "AI assistant" label and the human contact are always visible. */
export function ChatHeader({ locale, onHandoff, onNewConversation }: ChatHeaderProps) {
  const t = useTranslations("Chat");
  const common = useTranslations("Common");
  const names = { en: common("languages.en"), fr: common("languages.fr"), ar: common("languages.ar") };
  const themeLabels = { system: common("theme.system"), light: common("theme.light"), dark: common("theme.dark") };
  return (
    <header className="sticky top-0 z-[var(--z-header)] border-b border-line bg-bg">
      <div className="mx-auto flex h-16 max-w-5xl items-center gap-1 px-3 sm:gap-2 sm:px-6">
        <Link href="/" className="inline-flex shrink-0 items-center gap-2 rounded-full text-brand no-underline" aria-label={common("home")}>
          <Mark size={28} small />
          <span className="hidden text-xl font-bold text-ink md:inline">{common("brand")}</span>
        </Link>
        <span
          className="ms-1 inline-flex shrink-0 items-center rounded-full border border-line-strong px-2.5 py-1 text-xs font-bold sm:text-sm"
          data-testid="ai-label"
        >
          {common("aiAssistant")}
        </span>
        <span className="flex-1" />
        <button type="button" className="btn btn-ghost min-w-11 px-2.5 sm:px-3" onClick={(e) => onHandoff(e.currentTarget)} data-testid="handoff-button">
          <HeadsetIcon size={22} aria-hidden="true" />
          <span className="sr-only sm:not-sr-only">{t("handoff")}</span>
        </button>
        <LanguageSwitcher locale={locale} path="/chat" label={common("languageLabel")} names={names} />
        <ThemeToggle labels={themeLabels} />
        <button type="button" className="btn btn-ghost btn-icon" onClick={onNewConversation} aria-label={t("newConversation")} title={t("newConversation")} data-testid="new-conversation">
          <NotePencilIcon size={22} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
