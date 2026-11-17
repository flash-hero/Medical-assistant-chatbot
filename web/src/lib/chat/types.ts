/**
 * TypeScript mirror of core/schemas/events.py (JSON Schema: docs/contracts/chat-events.schema.json).
 * Ordering guarantees the UI relies on, but also defends against:
 *   meta first, done last; safety before any delta/answer; delta only for streamed answers;
 *   verify-then-release = status(verifying) then one answer; at most one error, followed by done.
 */

export const LOCALES = ["en", "fr", "ar"] as const;
export type ChatLocale = (typeof LOCALES)[number];

export const LANGUAGES = ["en", "fr", "ar", "es"] as const;
export type SourceLanguage = (typeof LANGUAGES)[number];

export const STAGES = ["checking", "searching", "writing", "verifying"] as const;
export type Stage = (typeof STAGES)[number];

export const SAFETY_KINDS = ["emergency", "self_harm", "harm_to_others", "abuse_disclosure"] as const;
export type SafetyKind = (typeof SAFETY_KINDS)[number];

export const INTENTS = [
  "medical_info",
  "medication",
  "symptom_info",
  "hospital_admin",
  "appointment",
  "smalltalk",
  "meta",
  "out_of_scope",
] as const;
export type Intent = (typeof INTENTS)[number];

export const ANSWER_MODES = ["streamed", "verified", "template", "abstain", "refusal"] as const;
export type AnswerMode = (typeof ANSWER_MODES)[number];

export const NOTICE_CODES = ["degraded", "source_language", "demo_mode", "session_limit_near", "handoff_available"] as const;
export type NoticeCode = (typeof NOTICE_CODES)[number];

export const FIELD_KINDS = ["text", "tel", "email", "date", "select", "textarea"] as const;
export type FieldKind = (typeof FIELD_KINDS)[number];

export interface ReleaseInfo {
  readonly app_version: string;
  readonly corpus_version: string;
  readonly prompt_hash: string;
  readonly models: Readonly<Record<string, string>>;
}

export interface Contact {
  readonly label: string;
  readonly number: string;
  readonly hours: string;
}

export interface Citation {
  readonly n: number;
  readonly title: string;
  readonly publisher: string;
  readonly url: string;
  readonly heading: string;
  readonly reviewed_on: string | null;
  readonly language: SourceLanguage;
  readonly snippet: string;
}

export interface FormField {
  readonly name: string;
  readonly label: string;
  readonly kind: FieldKind;
  readonly required: boolean;
  readonly options: readonly string[];
  readonly max_length: number;
}

export interface MetaEvent {
  readonly type: "meta";
  readonly turn_id: string;
  readonly session_id: string;
  readonly locale: ChatLocale;
  readonly demo_mode: boolean;
  readonly release: ReleaseInfo;
}

export interface StatusEvent {
  readonly type: "status";
  readonly stage: Stage;
}

export interface SafetyEvent {
  readonly type: "safety";
  readonly kind: SafetyKind;
  readonly template_id: string;
  readonly title: string;
  readonly message: string;
  readonly contacts: readonly Contact[];
  readonly sticky: boolean;
}

export interface DeltaEvent {
  readonly type: "delta";
  readonly text: string;
}

export interface AnswerEvent {
  readonly type: "answer";
  readonly text: string;
  readonly citations: readonly Citation[];
  readonly intent: Intent;
  readonly mode: AnswerMode;
  readonly verified: boolean;
  readonly replaces_stream: boolean;
  readonly source_language_note: boolean;
  readonly show_seek_care: boolean;
}

export interface NoticeEvent {
  readonly type: "notice";
  readonly code: NoticeCode;
  readonly message: string;
}

export interface FormEvent {
  readonly type: "form";
  readonly form_id: "appointment_request";
  readonly title: string;
  readonly description: string;
  readonly fields: readonly FormField[];
  readonly submit_url: string;
}

export interface ErrorEvent {
  readonly type: "error";
  readonly code: string;
  readonly message: string;
  readonly retry_after_s: number | null;
}

export interface DoneEvent {
  readonly type: "done";
  readonly turn_id: string;
  readonly turns_left: number;
}

export type ChatEvent =
  | MetaEvent
  | StatusEvent
  | SafetyEvent
  | DeltaEvent
  | AnswerEvent
  | NoticeEvent
  | FormEvent
  | ErrorEvent
  | DoneEvent;

export type ChatEventType = ChatEvent["type"];
