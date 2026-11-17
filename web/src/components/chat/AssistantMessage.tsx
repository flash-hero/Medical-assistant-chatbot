"use client";

import { SealCheckIcon, TranslateIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useId, useMemo } from "react";
import { Mark } from "@/components/brand/Mark";
import { directionOf } from "@/i18n/routing";
import { answerLanguage, foreignSourceLanguages } from "@/lib/chat/language";
import { displayText, type Turn } from "@/lib/chat/reducer";
import type { ChatLocale } from "@/lib/chat/types";
import { AppointmentForm } from "./AppointmentForm";
import { useChatActions } from "./ChatContext";
import { CitationList } from "./CitationList";
import { ErrorNotice } from "./ErrorNotice";
import { FeedbackBar } from "./FeedbackBar";
import { useSmoothText } from "./hooks/useSmoothText";
import { Markdown, type CitationRef } from "./Markdown";
import { NoticeList } from "./NoticeList";
import { SafetyBody } from "./SafetyBanner";
import { SeekCarePanel } from "./SeekCarePanel";
import { StatusLine } from "./StatusLine";

/** The answer in the language it is written in, which may not be the UI locale (review T1). */
function AnswerText({ turn, language }: { readonly turn: Turn; readonly language: ChatLocale }) {
  const t = useTranslations("Chat");
  const { openSource, locale } = useChatActions();
  const streamedOnly = turn.answer === null || !turn.answer.replaces_stream;
  const text = useSmoothText(displayText(turn), turn.streamed !== "" && streamedOnly);
  const citations = useMemo(
    () => new Map<number, CitationRef>((turn.answer?.citations ?? []).map((c) => [c.n, c])),
    [turn.answer],
  );
  if (text === "") return null;
  const onCite = (n: number, trigger: HTMLButtonElement) => {
    const citation = turn.answer?.citations.find((c) => c.n === n);
    if (citation) openSource(citation, language, trigger);
  };
  return (
    <div data-testid="answer-text" data-mode={turn.answer?.mode ?? "streaming"} lang={language} dir={directionOf(language)}>
      <Markdown
        text={text}
        citations={citations}
        onCite={onCite}
        citeLabel={(n, title) => t("citation", { n, title })}
        labelLang={language === locale ? undefined : locale}
      />
    </div>
  );
}

/** "The sources for this answer are in French and English", from the citations themselves (review T7). */
function SourceLanguageBadge({ turn, language }: { readonly turn: Turn; readonly language: ChatLocale }) {
  const t = useTranslations("Chat");
  const { locale } = useChatActions();
  const foreign = foreignSourceLanguages(turn.answer?.citations ?? [], language);
  if (!foreign) return null;
  const names = new Intl.ListFormat(locale, { type: "conjunction" }).format(foreign.languages.map((l) => t(`languageNames.${l}`)));
  return (
    <li className="flex items-center gap-1.5" data-testid="source-language-badge">
      <TranslateIcon size={18} aria-hidden="true" />
      {t("sourceLanguages", { scope: foreign.scope, languages: names })}
    </li>
  );
}

function AnswerBadges({ turn, language }: { readonly turn: Turn; readonly language: ChatLocale }) {
  const t = useTranslations("Chat");
  const answer = turn.answer;
  if (!answer) return null;
  const hasForeign = foreignSourceLanguages(answer.citations, language) !== null;
  if (!answer.verified && !hasForeign) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm font-semibold text-brand-ink">
      {answer.verified ? (
        <li className="flex items-center gap-1.5" data-testid="verified-badge">
          <SealCheckIcon size={18} aria-hidden="true" />
          {t("verified")}
        </li>
      ) : null}
      <SourceLanguageBadge turn={turn} language={language} />
    </ul>
  );
}

/** Streamed text that no confirmed answer replaced was never checked against its sources (review T9). */
function isUnverifiedPartial(turn: Turn): boolean {
  return turn.answer === null && turn.streamed !== "" && (turn.phase === "error" || turn.phase === "stopped");
}

function TurnNotes({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  return (
    <>
      {turn.phase === "stopped" ? (
        <p role="status" className="text-sm font-semibold text-ink-2" data-testid="stopped-note">
          {t("stopped")}
        </p>
      ) : null}
      {isUnverifiedPartial(turn) ? (
        <p role="status" className="rounded-xl border border-warn-line bg-warn-soft px-3 py-2 text-sm font-semibold text-warn-ink" data-testid="incomplete-note">
          {t("incomplete")}
        </p>
      ) : null}
    </>
  );
}

/** Safety events the server did not make sticky still reach the patient, inside their turn (review T13). */
function TurnSafety({ turn }: { readonly turn: Turn }) {
  const { hospital } = useChatActions();
  const titleId = useId();
  const inline = turn.safety.filter((s) => !s.sticky);
  if (inline.length === 0) return null;
  return (
    <div role="alert" aria-labelledby={titleId} className="rounded-2xl border border-danger-line bg-danger-soft p-4 text-danger-ink" data-testid="turn-safety">
      <SafetyBody events={inline} hospital={hospital} titleId={titleId} />
    </div>
  );
}

function TurnExtras({ turn, language }: { readonly turn: Turn; readonly language: ChatLocale }) {
  const { retry, newConversation } = useChatActions();
  const answer = turn.answer;
  return (
    <>
      {answer ? <CitationList citations={answer.citations} answerLanguage={language} /> : null}
      {answer?.show_seek_care ? <SeekCarePanel /> : null}
      {turn.form ? <AppointmentForm turn={turn} form={turn.form} /> : null}
      <NoticeList notices={turn.notices} />
      {turn.error ? <ErrorNotice error={turn.error} onRetry={() => retry(turn)} onNewConversation={newConversation} /> : null}
      {turn.phase === "done" && answer && turn.serverTurnId ? <FeedbackBar turn={turn} /> : null}
    </>
  );
}

/**
 * Ausculta's side of one turn. The chrome (labels, buttons) is in the UI locale; the answer text is in
 * its own language and direction.
 */
export function AssistantMessage({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat");
  const working = (turn.phase === "pending" || turn.phase === "streaming") && turn.answer === null;
  const language = answerLanguage(turn);
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
      <TurnSafety turn={turn} />
      {working ? <StatusLine stage={turn.stage} /> : null}
      <AnswerText turn={turn} language={language} />
      <TurnNotes turn={turn} />
      <AnswerBadges turn={turn} language={language} />
      <TurnExtras turn={turn} language={language} />
    </article>
  );
}
