"use client";

import { ArrowCounterClockwiseIcon, InfoIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { TurnError } from "@/lib/chat/reducer";

const KNOWN = new Set(["rate_limited", "overloaded", "service_paused", "session_exhausted", "unauthorized", "invalid_input", "network"]);
/** These errors are fixed by a new conversation (a new session), not by retrying. */
const NEEDS_NEW_SESSION = new Set(["session_exhausted", "unauthorized"]);

function useCountdown(seconds: number | null): number {
  const [left, setLeft] = useState(Math.ceil(seconds ?? 0));
  useEffect(() => {
    if (!seconds || seconds <= 0) return;
    const until = Date.now() + seconds * 1000;
    const timer = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) clearInterval(timer);
    }, 250);
    return () => clearInterval(timer);
  }, [seconds]);
  return left;
}

interface ErrorNoticeProps {
  readonly error: TurnError;
  readonly onRetry: () => void;
  readonly onNewConversation: () => void;
}

/** Localised, calm error with a Retry-After countdown; Retry stays disabled until it reaches zero. */
export function ErrorNotice({ error, onRetry, onNewConversation }: ErrorNoticeProps) {
  const t = useTranslations("Chat");
  const left = useCountdown(error.retryAfterS);
  const message = KNOWN.has(error.code) ? t(`errors.${error.code}`) : error.message || t("errors.unknown");
  const needsSession = NEEDS_NEW_SESSION.has(error.code);
  return (
    <div role="alert" className="grid gap-3 rounded-2xl border border-warn-line bg-warn-soft p-4 text-warn-ink" data-testid="turn-error" data-code={error.code}>
      <p className="flex items-start gap-2 font-semibold">
        <InfoIcon size={22} aria-hidden="true" className="mt-0.5 shrink-0" />
        <span>{message}</span>
      </p>
      {left > 0 ? (
        <p data-testid="retry-countdown" aria-live="off">
          {t("errors.retryIn", { seconds: left })}
        </p>
      ) : null}
      {needsSession ? (
        <button type="button" className="btn btn-primary w-fit" onClick={onNewConversation}>
          {t("newConversation")}
        </button>
      ) : (
        <button type="button" className="btn btn-quiet w-fit bg-surface" onClick={onRetry} disabled={left > 0}>
          <ArrowCounterClockwiseIcon size={20} aria-hidden="true" />
          {t("errors.retry")}
        </button>
      )}
    </div>
  );
}
