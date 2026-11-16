"use client";

import { useTranslations } from "next-intl";
import { directionOf } from "@/i18n/routing";
import type { Turn } from "@/lib/chat/reducer";
import { AssistantMessage } from "./AssistantMessage";

/** One question and its answer. Turns only exist after interaction, so the entrance never runs on SSR HTML. */
export function TurnView({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  return (
    <li className="enter-rise grid gap-5" data-testid="turn">
      <div className="ms-auto grid max-w-[85%] justify-items-end gap-1">
        <span className="sr-only">{t("you")}:</span>
        <p
          className="whitespace-pre-wrap break-words rounded-[1.25rem] rounded-ee-md bg-brand-soft px-4 py-3 text-brand-ink"
          lang={turn.locale}
          dir={directionOf(turn.locale)}
          data-testid="user-message"
        >
          {turn.question}
        </p>
      </div>
      <AssistantMessage turn={turn} />
    </li>
  );
}
