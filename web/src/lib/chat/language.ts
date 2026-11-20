/**
 * The real language of each part of a turn. The server may answer in the language of the question
 * rather than the UI locale (contract: `language` on answer and safety events); when it does not say,
 * the text itself is inspected (review T1, T7).
 */

import { detectTextLanguage } from "@/lib/i18n/text-language";
import { displayText, type Turn } from "./reducer";
import type { ChatLocale, Citation, SafetyEvent, SourceLanguage } from "./types";

/** Language of the answer shown for `turn`: the server's word, else detection, else the UI locale. */
export function answerLanguage(turn: Turn): ChatLocale {
  return turn.answer?.language ?? detectTextLanguage(displayText(turn)) ?? turn.locale;
}

/** Language of a safety event's own text, or null when neither the server nor the text tells. */
export function safetyLanguage(event: SafetyEvent): ChatLocale | null {
  return event.language ?? detectTextLanguage(`${event.title} ${event.message}`);
}

export interface ForeignSources {
  readonly languages: readonly SourceLanguage[];
  /** "all": every source is in another language; "some": part of them are in the answer's language. */
  readonly scope: "all" | "some";
}

/** Distinct source languages that differ from the answer's, in citation order; null when there is none. */
export function foreignSourceLanguages(citations: readonly Citation[], language: ChatLocale): ForeignSources | null {
  const foreign = [...new Set(citations.map((c) => c.language))].filter((l) => l !== language);
  if (foreign.length === 0) return null;
  return { languages: foreign, scope: citations.some((c) => c.language === language) ? "some" : "all" };
}
