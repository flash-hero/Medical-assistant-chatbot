"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { postAppointment, postFeedback, type FeedbackBody } from "@/lib/api/client";
import { chatReducer, INITIAL_CHAT_STATE, isTurnActive, type Turn } from "@/lib/chat/reducer";
import { runTurn } from "@/lib/chat/run-turn";
import { mergeSafetyLists } from "@/lib/chat/safety";
import type { ChatLocale, SafetyEvent } from "@/lib/chat/types";
import { MAX_MESSAGE_CHARS } from "@/lib/site";

function newTurnId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const NO_SAFETY: readonly SafetyEvent[] = [];

/**
 * Chat turns: reducer state, one active stream at a time, Stop via AbortController.
 * The emergency/crisis banners outlive "new conversation" for the rest of the page view, every kind
 * kept, highest priority first (review T2). `sessionTurnsLeft` seeds the questions-left counter.
 */
export function useTurns(token: string | null, locale: ChatLocale, sessionTurnsLeft: number | null) {
  const [state, dispatch] = useReducer(chatReducer, INITIAL_CHAT_STATE);
  const controllerRef = useRef<AbortController | null>(null);
  const [keptSafety, setKeptSafety] = useState<readonly SafetyEvent[]>(NO_SAFETY);
  const active = state.turns.some(isTurnActive);
  const safety = useMemo(() => mergeSafetyLists(keptSafety, state.safety), [keptSafety, state.safety]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const send = useCallback(
    (raw: string) => {
      const message = raw.trim();
      if (!token || message === "" || message.length > MAX_MESSAGE_CHARS || controllerRef.current) return false;
      const id = newTurnId();
      const controller = new AbortController();
      controllerRef.current = controller;
      if (sessionTurnsLeft !== null) dispatch({ type: "session/started", turnsLeft: sessionTurnsLeft });
      dispatch({ type: "turn/submit", id, question: message, locale });
      void runTurn({ token, message, locale, clientTurnId: id, signal: controller.signal }, dispatch).finally(() => {
        if (controllerRef.current === controller) controllerRef.current = null;
      });
      return true;
    },
    [token, locale, sessionTurnsLeft],
  );

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setKeptSafety((kept) => mergeSafetyLists(kept, state.safety));
    dispatch({ type: "conversation/reset" });
  }, [state.safety]);

  const sendFeedback = useCallback(
    async (turn: Turn, body: Omit<FeedbackBody, "turn_id">) => {
      if (!token || !turn.serverTurnId) throw new Error("no turn to rate");
      await postFeedback(token, { ...body, turn_id: turn.serverTurnId });
      dispatch({ type: "turn/feedback", id: turn.id, rating: body.rating });
    },
    [token],
  );

  const submitForm = useCallback(
    async (turn: Turn, body: Readonly<Record<string, string | boolean>>, idempotencyKey: string) => {
      if (!token || !turn.form) throw new Error("no form to submit");
      const result = await postAppointment(token, turn.form.submit_url, body, idempotencyKey);
      dispatch({ type: "turn/form-sent", id: turn.id, requestId: result.requestId, message: result.message });
    },
    [token],
  );

  return { state, safety, active, send, stop, reset, sendFeedback, submitForm };
}
