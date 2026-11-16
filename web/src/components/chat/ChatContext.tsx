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
  readonly submitForm: (turn: Turn, body: Readonly<Record<string, string | boolean>>) => Promise<void>;
  readonly openSource: (citation: Citation, answerLocale: ChatLocale, trigger: HTMLElement) => void;
  readonly openHandoff: (trigger: HTMLElement) => void;
}

const ChatContext = createContext<ChatActions | null>(null);

export const ChatProvider = ChatContext.Provider;

export function useChatActions(): ChatActions {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChatActions must be used inside <ChatProvider>");
  return value;
}
