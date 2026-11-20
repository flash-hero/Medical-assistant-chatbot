"use client";

import { createContext, useContext } from "react";
import type { FeedbackBody, PublicHospital } from "@/lib/api/client";
import type { Turn } from "@/lib/chat/reducer";
import type { ChatLocale, Citation } from "@/lib/chat/types";

export interface ChatActions {
  readonly locale: ChatLocale;
  readonly hospital: PublicHospital | null;
  readonly demoBannerShown: boolean;
  readonly send: (question: string) => boolean;
  readonly retry: (turn: Turn) => void;
  readonly newConversation: () => void;
  readonly sendFeedback: (turn: Turn, body: Omit<FeedbackBody, "turn_id">) => Promise<void>;
  /** `idempotencyKey` is the same for a retried, unchanged request (review T14). */
  readonly submitForm: (turn: Turn, body: Readonly<Record<string, string | boolean>>, idempotencyKey: string) => Promise<void>;
  /** `answerLanguage` is the language the answer is written in, which may differ from the UI locale. */
  readonly openSource: (citation: Citation, answerLanguage: ChatLocale, trigger: HTMLElement) => void;
  readonly openHandoff: (trigger: HTMLElement) => void;
}

const ChatContext = createContext<ChatActions | null>(null);

export const ChatProvider = ChatContext.Provider;

export function useChatActions(): ChatActions {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChatActions must be used inside <ChatProvider>");
  return value;
}
