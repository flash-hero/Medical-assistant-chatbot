"use client";

import { SealCheckIcon } from "@phosphor-icons/react/dist/ssr/SealCheck";
import { TranslateIcon } from "@phosphor-icons/react/dist/ssr/Translate";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { Mark } from "@/components/brand/Mark";
import { directionOf } from "@/i18n/routing";
import { displayText, type Turn } from "@/lib/chat/reducer";
import { AppointmentForm } from "./AppointmentForm";
import { useChatActions } from "./ChatContext";
import { CitationList } from "./CitationList";
import { ErrorNotice } from "./ErrorNotice";
import { FeedbackBar } from "./FeedbackBar";
import { useSmoothText } from "./hooks/useSmoothText";
import { Markdown, type CitationRef } from "./Markdown";
import { NoticeList } from "./NoticeList";
import { SeekCarePanel } from "./SeekCarePanel";
import { StatusLine } from "./StatusLine";

function AnswerText({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  const { openSource } = useChatActions();
  const streamedOnly = turn.answer === null || !turn.answer.replaces_stream;
  const text = useSmoothText(displayText(turn), turn.streamed !== "" && streamedOnly);
  const citations = useMemo(
    () => new Map<number, CitationRef>((turn.answer?.citations ?? []).map((c) => [c.n, c])),
    [turn.answer],
  );
  if (text === "") return null;
  const onCite = (n: number, trigger: HTMLButtonElement) => {
    const citation = turn.answer?.citations.find((c) => c.n === n);
    if (citation) openSource(citation, turn.locale, trigger);
  };
  return (
    <div data-testid="answer-text" data-mode={turn.answer?.mode ?? "streaming"}>
      <Markdown text={text} citations={citations} onCite={onCite} citeLabel={(n, title) => t("citation", { n, title })} />
    </div>
  );
}

function AnswerBadges({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  const answer = turn.answer;
  if (!answer || (!answer.verified && !answer.source_language_note)) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm font-semibold text-brand-ink">
      {answer.verified ? (
        <li className="flex items-center gap-1.5" data-testid="verified-badge">
          <SealCheckIcon size={18} aria-hidden="true" />
          {t("verified")}
        </li>
      ) : null}
      {answer.source_language_note ? (
        <li className="flex items-center gap-1.5">
          <TranslateIcon size={18} aria-hidden="true" />
          {t("sourceLanguage")}
        </li>
      ) : null}
    </ul>
  );
}

function TurnExtras({ turn }: { readonly turn: Turn }) {
  const { retry, newConversation } = useChatActions();
  const t = useTranslations("Chat");
  const answer = turn.answer;
  return (
    <>
      {answer ? <CitationList citations={answer.citations} answerLocale={turn.locale} /> : null}
      {answer?.show_seek_care ? <SeekCarePanel /> : null}
      {turn.form ? <AppointmentForm turn={turn} form={turn.form} /> : null}
      <NoticeList notices={turn.notices} />
      {turn.phase === "stopped" ? <p className="text-sm font-semibold text-ink-2" data-testid="stopped-note">{t("stopped")}</p> : null}
      {turn.error ? <ErrorNotice error={turn.error} onRetry={() => retry(turn)} onNewConversation={newConversation} /> : null}
      {turn.phase === "done" && answer && turn.serverTurnId ? <FeedbackBar turn={turn} /> : null}
    </>
  );
}

/** Ausculta's side of one turn. The answer is in the turn's language and direction. */
export function AssistantMessage({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  const working = (turn.phase === "pending" || turn.phase === "streaming") && turn.answer === null;
  return (
    <article
      className="grid gap-3"
      lang={turn.locale}
      dir={directionOf(turn.locale)}
      aria-label={t("assistant")}
      data-testid="assistant-message"
      data-phase={turn.phase}
    >
      <p className="flex items-center gap-2 text-sm font-bold">
        <Mark size={22} small className="text-brand" />
        {t("assistant")}
      </p>
      {working ? <StatusLine stage={turn.stage} /> : null}
      <AnswerText turn={turn} />
      <AnswerBadges turn={turn} />
      <TurnExtras turn={turn} />
    </article>
  );
}
