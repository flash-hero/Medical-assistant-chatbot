"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { isDemoMode } from "@/lib/chat/demo-mode";
import type { Turn } from "@/lib/chat/reducer";
import type { ChatLocale, Citation } from "@/lib/chat/types";
import type { ChatActions } from "../ChatContext";
import type { OpenSource } from "../SourceDrawer";
import { useSession } from "./useSession";
import { useTurns } from "./useTurns";

/** Everything the chat screen needs, wired once: session, turns, drawer, handoff, focus return. */
export function useChatController(locale: ChatLocale) {
  const { state: session, hospital, renew } = useSession(locale);
  const token = session.status === "ready" ? session.session.token : null;
  const sessionTurnsLeft = session.status === "ready" ? session.session.turnsLeft : null;
  const turns = useTurns(token, locale, sessionTurnsLeft);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const handoffRef = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [source, setSource] = useState<OpenSource | null>(null);
  const demoMode = isDemoMode(session.status === "ready" ? session.session.demoMode : null, turns.state.demoMode);
  const turnsLeft = turns.state.turnsLeft ?? sessionTurnsLeft;

  const { send, reset } = turns;
  const newConversation = useCallback(() => {
    reset();
    renew();
    inputRef.current?.focus();
  }, [reset, renew]);

  const closeSource = useCallback(() => {
    setSource(null);
    returnFocus.current?.focus();
  }, []);

  const closeHandoff = useCallback(() => returnFocus.current?.focus(), []);

  const actions = useMemo<ChatActions>(
    () => ({
      locale,
      hospital,
      demoBannerShown: demoMode,
      send,
      retry: (turn: Turn) => {
        send(turn.question);
      },
      newConversation,
      sendFeedback: turns.sendFeedback,
      submitForm: turns.submitForm,
      openSource: (citation: Citation, answerLanguage: ChatLocale, trigger: HTMLElement) => {
        returnFocus.current = trigger;
        setSource({ citation, answerLanguage });
      },
      openHandoff: (trigger: HTMLElement) => {
        returnFocus.current = trigger;
        handoffRef.current?.showModal();
      },
    }),
    [locale, hospital, demoMode, send, newConversation, turns.sendFeedback, turns.submitForm],
  );

  return { session, hospital, renew, turns, actions, inputRef, handoffRef, source, closeSource, closeHandoff, demoMode, turnsLeft };
}
