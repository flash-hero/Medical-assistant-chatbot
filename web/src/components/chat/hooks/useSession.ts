"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, createSession, getHospital, type PublicHospital, type Session } from "@/lib/api/client";
import { isAbortError } from "@/lib/api/errors";
import type { ChatLocale } from "@/lib/chat/types";

export type SessionState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly session: Session }
  | { readonly status: "error"; readonly code: string; readonly retryAfterS: number | null };

const LOADING: SessionState = { status: "loading" };

/**
 * POST /session on load (and on "new conversation"), plus GET /hospital for the always-reachable human
 * contact. The hospital profile from either response is kept; the dedicated endpoint wins.
 */
export function useSession(locale: ChatLocale) {
  const [state, setState] = useState<SessionState>(LOADING);
  const [hospital, setHospital] = useState<PublicHospital | null>(null);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    createSession(locale, controller.signal)
      .then((session) => {
        setState({ status: "ready", session });
        if (session.hospital) setHospital((current) => current ?? session.hospital);
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        const apiError = error instanceof ApiError ? error : null;
        setState({ status: "error", code: apiError?.code ?? "unknown", retryAfterS: apiError?.retryAfterS ?? null });
      });
    return () => controller.abort();
  }, [locale, generation]);

  useEffect(() => {
    const controller = new AbortController();
    getHospital(locale, controller.signal)
      .then(setHospital)
      .catch(() => undefined); // the session response may still carry the profile
    return () => controller.abort();
  }, [locale]);

  const renew = useCallback(() => {
    setState(LOADING);
    setGeneration((g) => g + 1);
  }, []);

  return { state, hospital, renew };
}
