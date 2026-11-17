/** Test helpers: render chat components with real messages (EN/FR/AR) and a stubbed ChatContext. */
import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";
import { ChatProvider, type ChatActions } from "@/components/chat/ChatContext";
import type { PublicHospital } from "@/lib/api/hospital";
import type { Turn } from "@/lib/chat/reducer";
import type { AnswerEvent, ChatLocale, Citation, SafetyEvent } from "@/lib/chat/types";
import ar from "@/messages/ar.json";
import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

export const MESSAGES = { en, fr, ar } as const;

const contact = (label: string, number: string) => ({ label, number, hours: "" });

export const HOSPITAL: PublicHospital = {
  id: "demo",
  name: "Demo Hospital",
  isDemo: true,
  address: "",
  mainPhone: contact("Switchboard", "+33 4 00 00 00 00"),
  emergency: contact("Emergency", "112"),
  crisisLines: [contact("Crisis line", "3114")],
  handoff: contact("Front desk", "+33 4 00 00 00 01"),
  visitingHours: "",
  departments: [
    { id: "cardiology", name: "Cardiologie", location: "", hours: "", acceptsAppointments: true },
    { id: "general_medicine", name: "Médecine générale", location: "", hours: "", acceptsAppointments: true },
  ],
};

export function answer(overrides: Partial<AnswerEvent> = {}): AnswerEvent {
  return {
    type: "answer",
    text: "An HbA1c test measures your average blood sugar [1].",
    citations: [],
    intent: "medical_info",
    mode: "verified",
    verified: true,
    replaces_stream: false,
    source_language_note: false,
    show_seek_care: false,
    language: null,
    ...overrides,
  };
}

export function citation(n: number, language: Citation["language"], overrides: Partial<Citation> = {}): Citation {
  return {
    n,
    title: `Source ${n}`,
    publisher: "Publisher",
    url: `https://example.org/${n}`,
    heading: "",
    reviewed_on: null,
    language,
    snippet: "Excerpt.",
    ...overrides,
  };
}

export function safety(kind: SafetyEvent["kind"], overrides: Partial<SafetyEvent> = {}): SafetyEvent {
  return {
    type: "safety",
    kind,
    template_id: `${kind}.v1`,
    title: `${kind} title`,
    message: `${kind} message`,
    contacts: [],
    sticky: true,
    language: null,
    ...overrides,
  };
}

export function turn(overrides: Partial<Turn> = {}): Turn {
  return {
    id: "c1",
    question: "What does an HbA1c test measure?",
    locale: "en",
    serverTurnId: "srv-1",
    phase: "done",
    stage: null,
    streamed: "",
    answer: null,
    safety: [],
    notices: [],
    form: null,
    formResult: null,
    error: null,
    feedback: null,
    ...overrides,
  };
}

export function stubActions(locale: ChatLocale, overrides: Partial<ChatActions> = {}): ChatActions {
  return {
    locale,
    hospital: HOSPITAL,
    demoBannerShown: true,
    send: vi.fn(() => true),
    retry: vi.fn(),
    newConversation: vi.fn(),
    sendFeedback: vi.fn().mockResolvedValue(undefined),
    submitForm: vi.fn().mockResolvedValue(undefined),
    openSource: vi.fn(),
    openHandoff: vi.fn(),
    ...overrides,
  };
}

/** Reduced motion on, so streamed text appears at once. */
export function reduceMotion(): void {
  const list = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", vi.fn(() => list));
}

export function IntlWrapper({ locale, children }: { readonly locale: ChatLocale; readonly children: ReactNode }) {
  return (
    <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="UTC">
      {children}
    </NextIntlClientProvider>
  );
}

export function renderChat(
  ui: ReactElement,
  options: { readonly locale?: ChatLocale; readonly actions?: Partial<ChatActions> } = {},
): RenderResult & { readonly actions: ChatActions; readonly rerenderChat: (next: ReactElement) => void } {
  const locale = options.locale ?? "en";
  const actions = stubActions(locale, options.actions);
  const wrap = (node: ReactElement) => (
    <IntlWrapper locale={locale}>
      <ChatProvider value={actions}>{node}</ChatProvider>
    </IntlWrapper>
  );
  const result = render(wrap(ui));
  return { ...result, actions, rerenderChat: (next) => result.rerender(wrap(next)) };
}
