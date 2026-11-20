"use client";

import { PaperPlaneRightIcon, StopIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { DEFAULT_TURNS_PER_SESSION, MAX_MESSAGE_CHARS } from "@/lib/site";
import { HEALTH_TEXT_PROPS } from "./health-text";

interface ComposerProps {
  readonly inputRef: RefObject<HTMLTextAreaElement | null>;
  readonly active: boolean;
  readonly ready: boolean;
  readonly turnsLeft: number | null;
  readonly onSend: (text: string) => boolean;
  readonly onStop: () => void;
}

const WARN_AT = 1800;

type Blocked = "connecting" | "busy" | "exhausted" | "tooLong";

function blockedReason(ready: boolean, active: boolean, turnsLeft: number | null, length: number): Blocked | null {
  if (!ready) return "connecting";
  if (active) return "busy";
  if (turnsLeft === 0) return "exhausted";
  return length > MAX_MESSAGE_CHARS ? "tooLong" : null;
}

/**
 * Enter sends, Shift+Enter adds a line (IME composition is respected). Stop replaces Send while answering.
 * A send that cannot happen says why instead of doing nothing (review T18). When Stop disappears while it
 * has focus (the answer stopped or finished), focus moves to the message box rather than the page (T8).
 */
export function Composer({ inputRef, active, ready, turnsLeft, onSend, onStop }: ComposerProps) {
  const t = useTranslations("Chat");
  const id = useId();
  const [text, setText] = useState("");
  const [tried, setTried] = useState(false);
  const stopFocused = useRef(false);
  const blocked = blockedReason(ready, active, turnsLeft, text.length);
  const canSend = blocked === null && text.trim() !== "";
  const notice = tried && text.trim() !== "" ? blocked : null;

  useEffect(() => {
    if (active || !stopFocused.current) return;
    stopFocused.current = false;
    inputRef.current?.focus();
  }, [active, inputRef]);

  const submit = () => {
    if (text.trim() === "") return;
    setTried(true);
    if (canSend && onSend(text)) {
      setText("");
      setTried(false);
    }
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    submit();
  };

  return (
    <form
      className="grid gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor={`${id}-input`} className="sr-only">
        {t("inputLabel")}
      </label>
      <div className="flex items-end gap-2 rounded-[1.5rem] border border-line-strong bg-surface p-2 ps-4 focus-within:border-brand">
        <textarea
          ref={inputRef}
          id={`${id}-input`}
          data-testid="composer-input"
          className="composer-input max-h-48 min-h-11 flex-1 resize-none bg-transparent py-2.5 outline-none"
          rows={1}
          dir="auto"
          value={text}
          maxLength={MAX_MESSAGE_CHARS}
          placeholder={t("placeholder")}
          aria-describedby={`${id}-hint ${id}-count ${id}-blocked`}
          onChange={(e) => {
            setText(e.target.value);
            setTried(false);
          }}
          onKeyDown={onKeyDown}
          {...HEALTH_TEXT_PROPS}
        />
        {active ? (
          <button
            type="button"
            className="btn btn-quiet shrink-0 bg-surface"
            onClick={onStop}
            onFocus={() => {
              stopFocused.current = true;
            }}
            onBlur={(e) => {
              // Removal while focused gives no related target: keep the flag so focus can move on.
              if (e.relatedTarget) stopFocused.current = false;
            }}
            data-testid="stop-button"
          >
            <StopIcon size={20} weight="fill" aria-hidden="true" />
            {t("stop")}
          </button>
        ) : (
          <button type="submit" className="btn btn-primary btn-icon shrink-0" disabled={!canSend} aria-label={t("send")} data-testid="send-button">
            <PaperPlaneRightIcon size={22} weight="fill" aria-hidden="true" className="rtl:-scale-x-100" />
          </button>
        )}
      </div>
      {/* Always in the accessibility tree (a live region), out of the layout while empty. */}
      <p id={`${id}-blocked`} role="status" className="px-2 text-sm font-semibold text-warn-ink empty:sr-only" data-testid="send-blocked">
        {notice ? t(`sendBlocked.${notice}`) : null}
      </p>
      <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 px-2 text-sm text-ink-2">
        <span id={`${id}-hint`}>{t("hint")}</span>
        <span className="flex gap-4">
          {turnsLeft !== null ? (
            <span data-testid="turns-left">{t("turnsLeft", { count: turnsLeft })}</span>
          ) : (
            // Until the session answers, an invisible copy holds the slot so the row does not shift or wrap later.
            <span className="invisible" aria-hidden="true">
              {t("turnsLeft", { count: DEFAULT_TURNS_PER_SESSION })}
            </span>
          )}
          <span id={`${id}-count`} className={`whitespace-nowrap tabular-nums ${text.length >= WARN_AT ? "font-bold text-warn-ink" : ""}`} data-testid="char-count">
            {t("counter", { count: text.length, max: MAX_MESSAGE_CHARS })}
          </span>
        </span>
      </div>
    </form>
  );
}
