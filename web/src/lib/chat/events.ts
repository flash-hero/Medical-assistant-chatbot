import type { SseMessage } from "@/lib/sse/parser";
import {
  asArray,
  asBool,
  asHttpUrl,
  asInt,
  asPhone,
  asString,
  asTruncatedString,
  isIsoDate,
  isRecord,
  oneOf,
  uniqueBy,
  type Json,
} from "@/lib/validate";
import {
  ANSWER_MODES,
  FIELD_KINDS,
  INTENTS,
  LANGUAGES,
  LOCALES,
  NOTICE_CODES,
  SAFETY_KINDS,
  STAGES,
  type AnswerEvent,
  type ChatEvent,
  type Citation,
  type Contact,
  type DoneEvent,
  type ErrorEvent,
  type FormEvent,
  type FormField,
  type MetaEvent,
  type NoticeEvent,
  type SafetyEvent,
} from "./types";

export type ParseResult =
  | { readonly ok: true; readonly event: ChatEvent }
  | { readonly ok: false; readonly reason: "invalid_json" | "unknown_event" | "invalid_payload" };

export const MAX_SNIPPET_CHARS = 600;
export const MAX_RETRY_AFTER_S = 3600;
export const MAX_SAFETY_TITLE_CHARS = 500;
export const MAX_SAFETY_MESSAGE_CHARS = 4000;
const MAX_SAFETY_CONTACTS = 10;
const MAX_CITATIONS = 50;
const MAX_OPTIONS = 100;
const FIELD_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const RESERVED_FIELD_NAMES = new Set(["constructor", "prototype"]);
/** The UI always renders its own consent checkbox; a server-sent field with that name is dropped. */
const UI_OWNED_FIELDS = new Set(["consent"]);

function parseMeta(p: Json): MetaEvent | null {
  const release = p.release;
  if (!isRecord(release) || !isRecord(release.models)) return null;
  const models: Record<string, string> = {};
  for (const [key, value] of Object.entries(release.models)) {
    const model = asString(value, 200);
    if (model !== null) models[key] = model;
  }
  const turn_id = asString(p.turn_id, 200);
  const session_id = asString(p.session_id, 200);
  const locale = oneOf(p.locale, LOCALES);
  const demo_mode = asBool(p.demo_mode);
  const app_version = asString(release.app_version, 200);
  const corpus_version = asString(release.corpus_version, 200);
  const prompt_hash = asString(release.prompt_hash, 200);
  if (turn_id === null || session_id === null || locale === null || demo_mode === null) return null;
  if (app_version === null || corpus_version === null || prompt_hash === null) return null;
  return { type: "meta", turn_id, session_id, locale, demo_mode, release: { app_version, corpus_version, prompt_hash, models } };
}

function parseContact(raw: unknown): Contact | null {
  if (!isRecord(raw)) return null;
  const label = asString(raw.label, 200);
  const number = asPhone(raw.number);
  const hours = asString(raw.hours, 200) ?? "";
  return label !== null && number !== null ? { label, number, hours } : null;
}

/**
 * The safety banner must survive contract drift (review T4): unknown kinds count as emergencies,
 * over-long text is cut, invalid contacts are dropped one by one. An empty title or message tells
 * the UI to use its own localised fallback text; empty contacts make it use the hospital profile.
 */
function parseSafety(p: Json): SafetyEvent {
  const contacts = (asArray(p.contacts) ?? []).map(parseContact).filter((c): c is Contact => c !== null);
  return {
    type: "safety",
    kind: oneOf(p.kind, SAFETY_KINDS) ?? "emergency",
    template_id: asTruncatedString(p.template_id, 200) ?? "",
    title: asTruncatedString(p.title, MAX_SAFETY_TITLE_CHARS) ?? "",
    message: asTruncatedString(p.message, MAX_SAFETY_MESSAGE_CHARS) ?? "",
    contacts: uniqueBy(contacts, (c) => c.number).slice(0, MAX_SAFETY_CONTACTS),
    sticky: asBool(p.sticky, true) ?? true,
    language: oneOf(p.language, LOCALES),
  };
}

/** A safety event that could not be read at all still shows the localised emergency banner. */
export const FALLBACK_SAFETY: SafetyEvent = Object.freeze({
  type: "safety",
  kind: "emergency",
  template_id: "",
  title: "",
  message: "",
  contacts: Object.freeze([]) as readonly Contact[],
  sticky: true,
  language: null,
});

function parseCitation(raw: unknown): Citation | null {
  if (!isRecord(raw)) return null;
  const n = asInt(raw.n, 1, 999);
  const title = asString(raw.title, 1000);
  const publisher = asString(raw.publisher, 500);
  const url = asHttpUrl(raw.url);
  const heading = raw.heading === undefined ? "" : asString(raw.heading, 1000);
  // A date that is not a real calendar day ("2025-13-45") is dropped, not the citation (review T11).
  const reviewed_on = isIsoDate(raw.reviewed_on) ? raw.reviewed_on : null;
  const language = oneOf(raw.language, LANGUAGES);
  const snippet = asString(raw.snippet, 100_000);
  if (n === null || title === null || publisher === null || url === null || heading === null) return null;
  if (language === null || snippet === null) return null;
  return { n, title, publisher, url, heading, reviewed_on, language, snippet: snippet.slice(0, MAX_SNIPPET_CHARS) };
}

function parseAnswer(p: Json): AnswerEvent | null {
  const text = asString(p.text, 50_000);
  const rawCitations = asArray(p.citations);
  const intent = oneOf(p.intent, INTENTS);
  const mode = oneOf(p.mode, ANSWER_MODES);
  const verified = asBool(p.verified);
  const replaces_stream = asBool(p.replaces_stream, false);
  const source_language_note = asBool(p.source_language_note, false);
  const show_seek_care = asBool(p.show_seek_care, false);
  if (text === null || rawCitations === null || intent === null || mode === null || verified === null) return null;
  if (replaces_stream === null || source_language_note === null || show_seek_care === null) return null;
  const parsed = rawCitations.map(parseCitation).filter((c): c is Citation => c !== null);
  const citations = uniqueBy(parsed, (c) => c.n).slice(0, MAX_CITATIONS);
  const language = oneOf(p.language, LOCALES);
  return { type: "answer", text, citations, intent, mode, verified, replaces_stream, source_language_note, show_seek_care, language };
}

function parseField(raw: unknown): FormField | null {
  if (!isRecord(raw)) return null;
  const name = asString(raw.name, 64);
  const label = asString(raw.label, 300);
  const kind = oneOf(raw.kind, FIELD_KINDS);
  const required = asBool(raw.required, false);
  const rawOptions = asArray(raw.options);
  const max_length = raw.max_length === undefined ? 200 : asInt(raw.max_length, 1, 5000);
  if (name === null || !FIELD_NAME.test(name) || RESERVED_FIELD_NAMES.has(name)) return null;
  if (label === null || kind === null || required === null || rawOptions === null || max_length === null) return null;
  const options = rawOptions.map((o) => asString(o, 300));
  if (options.some((o) => o === null)) return null;
  const unique = uniqueBy(options as string[], (o) => o).slice(0, MAX_OPTIONS);
  return { name, label, kind, required, options: unique, max_length };
}

/** The form posts personal data: only a same-origin API path is acceptable. */
export function isSafeSubmitUrl(url: string): boolean {
  return /^\/api\/v1\/[a-z0-9_\-/]+$/.test(url) && !url.includes("//") && !url.includes("..");
}

function parseForm(p: Json): FormEvent | null {
  if (p.form_id !== "appointment_request") return null;
  const title = asString(p.title, 300);
  const description = asString(p.description, 2000);
  const rawFields = asArray(p.fields);
  const submit_url = p.submit_url === undefined ? "/api/v1/appointments" : asString(p.submit_url, 200);
  if (title === null || description === null || rawFields === null || submit_url === null) return null;
  if (!isSafeSubmitUrl(submit_url) || rawFields.length === 0 || rawFields.length > 20) return null;
  const fields = rawFields
    .filter((f) => !(isRecord(f) && typeof f.name === "string" && UI_OWNED_FIELDS.has(f.name)))
    .map(parseField);
  if (fields.some((f) => f === null)) return null;
  const unique = uniqueBy(fields as FormField[], (f) => f.name);
  return { type: "form", form_id: "appointment_request", title, description, fields: unique, submit_url };
}

function parseError(p: Json): ErrorEvent | null {
  const code = asString(p.code, 100);
  const message = asString(p.message, 2000);
  const retry = p.retry_after_s ?? null;
  if (code === null || message === null) return null;
  if (retry !== null && (typeof retry !== "number" || !Number.isFinite(retry) || retry < 0)) return null;
  const retry_after_s = retry === null ? null : Math.min(retry, MAX_RETRY_AFTER_S);
  return { type: "error", code, message, retry_after_s };
}

function parseDone(p: Json): DoneEvent | null {
  const turn_id = asString(p.turn_id, 200);
  const turns_left = asInt(p.turns_left, 0, 10_000);
  return turn_id !== null && turns_left !== null ? { type: "done", turn_id, turns_left } : null;
}

function parseNotice(p: Json): NoticeEvent | null {
  const code = oneOf(p.code, NOTICE_CODES);
  const message = asString(p.message, 2000);
  return code !== null && message !== null ? { type: "notice", code, message } : null;
}

const PARSERS: Readonly<Record<ChatEvent["type"], (p: Json) => ChatEvent | null>> = {
  meta: parseMeta,
  status: (p) => {
    const stage = oneOf(p.stage, STAGES);
    return stage === null ? null : { type: "status", stage };
  },
  safety: parseSafety,
  delta: (p) => {
    const text = asString(p.text, 20_000);
    return text === null ? null : { type: "delta", text };
  },
  answer: parseAnswer,
  notice: parseNotice,
  form: parseForm,
  error: parseError,
  done: parseDone,
};

function isKnownType(type: string): type is ChatEvent["type"] {
  return Object.prototype.hasOwnProperty.call(PARSERS, type);
}

function parsePayload(message: SseMessage & { readonly event: ChatEvent["type"] }): ParseResult {
  let payload: unknown;
  try {
    payload = JSON.parse(message.data);
  } catch {
    return { ok: false, reason: "invalid_json" };
  }
  if (!isRecord(payload) || (payload.type !== undefined && payload.type !== message.event)) {
    return { ok: false, reason: "invalid_payload" };
  }
  const event = PARSERS[message.event](payload);
  return event === null ? { ok: false, reason: "invalid_payload" } : { ok: true, event };
}

/**
 * Validate one SSE message against the chat event contract. Unknown types are ignored, not errors.
 * A `safety` message is never dropped: whatever arrives, the patient sees an emergency banner.
 */
export function parseChatEvent(message: SseMessage): ParseResult {
  const event = message.event;
  if (!isKnownType(event)) return { ok: false, reason: "unknown_event" };
  const result = parsePayload({ ...message, event });
  if (result.ok || event !== "safety") return result;
  return { ok: true, event: FALLBACK_SAFETY };
}
