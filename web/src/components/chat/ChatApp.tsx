"use client";

import { InfoIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useRef } from "react";
import type { ChatLocale } from "@/lib/chat/types";
import { ChatHeader } from "./ChatHeader";
import { ChatProvider } from "./ChatContext";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";
import { HandoffDialog } from "./HandoffDialog";
import { useAnnouncements } from "./hooks/useAnnouncements";
import { useChatController } from "./hooks/useChatController";
import { useStickToBottom } from "./hooks/useStickToBottom";
import { SafetyBanner } from "./SafetyBanner";
import { SourceDrawer } from "./SourceDrawer";
import { TurnView } from "./TurnView";

function DemoBanner() {
  const t = useTranslations("Chat");
  return (
    <p className="border-b border-warn-line bg-warn-soft text-warn-ink" data-testid="demo-banner">
      <span className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-2 text-sm font-semibold sm:px-6">
        <InfoIcon size={18} aria-hidden="true" className="shrink-0" />
        {t("demoBanner")}
      </span>
    </p>
  );
}

export function ChatApp({ locale }: { readonly locale: ChatLocale }) {
  const t = useTranslations("Chat");
  const { session, hospital, renew, turns, actions, inputRef, handoffRef, source, closeSource, closeHandoff, demoMode, turnsLeft } =
    useChatController(locale);
  const { state, safety, active, stop } = turns;
  const lastTurn = state.turns.at(-1);
  const announcement = useAnnouncements(lastTurn, t("answering"));
  const sentinel = useRef<HTMLDivElement>(null);
  useStickToBottom(sentinel, lastTurn);
  const ready = session.status === "ready";
  const pick = (question: string) => {
    actions.send(question);
    inputRef.current?.focus();
  };

  return (
    <ChatProvider value={actions}>
          <div className="flex min-h-dvh flex-col">
            <ChatHeader locale={locale} onHandoff={actions.openHandoff} onNewConversation={actions.newConversation} />
            {demoMode ? <DemoBanner /> : null}
            <SafetyBanner safety={safety} />
            <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl flex-1 px-4 outline-none sm:px-6">
              <h1 className="sr-only">{t("title")}</h1>
              {state.turns.length === 0 ? (
                <EmptyState onPick={pick} disabled={!ready} />
              ) : (
                <ol className="grid gap-10 py-8" aria-label={t("title")} data-testid="conversation">
                  {state.turns.map((turn) => (
                    <TurnView key={turn.id} turn={turn} />
                  ))}
                </ol>
              )}
              {session.status === "error" ? (
                <div className="pb-6" data-testid="session-error">
                  <ErrorNotice error={{ code: session.code, message: t("sessionError"), retryAfterS: session.retryAfterS }} onRetry={renew} onNewConversation={renew} />
                </div>
              ) : null}
              {session.status === "loading" && state.turns.length === 0 ? <p className="pb-4 text-sm text-ink-2">{t("connecting")}</p> : null}
              <div ref={sentinel} className="h-px" />
            </main>
            <div className="sticky bottom-0 z-[var(--z-sticky)] border-t border-line bg-bg">
              <div className="mx-auto max-w-3xl px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-6">
                <Composer inputRef={inputRef} active={active} ready={ready} turnsLeft={turnsLeft} onSend={actions.send} onStop={stop} />
              </div>
            </div>
            <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-region">
              <span key={announcement.id}>{announcement.text}</span>
            </div>
            <SourceDrawer source={source} onClose={closeSource} />
            <HandoffDialog ref={handoffRef} hospital={hospital} onClose={closeHandoff} />
          </div>
    </ChatProvider>
  );
}
