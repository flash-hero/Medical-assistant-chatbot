/**
 * Scripted chat scenarios for the mock API, chosen by keywords in the user's message (EN / FR / AR).
 * Each script is either a pre-stream JSON error or a list of SSE events with delays, following
 * docs/contracts/chat-events.schema.json. All content is synthetic.
 */
import { CITATIONS, HOSPITAL, RELEASE } from "./fixtures.mjs";
import { appointmentFormEvent } from "./form-scenario.mjs";
import { TEXT } from "./texts.mjs";

/** Order matters: safety scenarios are checked first, exactly like the real pipeline. */
const KEYWORDS = [
  ["self_harm", [/kill myself/i, /end my life/i, /suicid/i, /me tuer/i, /mettre fin à mes jours/i, /انتحار/, /أنهي حياتي/, /أقتل نفسي/]],
  ["emergency", [/chest pain/i, /can'?t breathe/i, /douleur (thoracique|dans la poitrine)/i, /du mal à respirer/i, /ألم في الصدر/, /لا أستطيع التنفس/]],
  ["injection", [/ignore (all|previous|the) (previous )?instructions/i, /system prompt/i, /ignore(z)? (les|toutes les) instructions/i, /تجاهل التعليمات/]],
  ["rate_limited", [/\b429\b/, /rate limit/i]],
  ["overloaded", [/\b503\b/, /overload/i, /surcharg/i, /ضغط كبير/]],
  ["unauthorized", [/\b401\b/, /expired session/i]],
  ["slow", [/\bslow\b/i, /\blent(e)?\b/i, /ببطء/]],
  ["fail", [/\bfail\b/i, /échec/i, /فشل/]],
  ["replaced", [/\bdraft\b/i, /brouillon/i, /مسودة/]],
  ["appointment", [/appointment/i, /rendez-vous/i, /موعد/]],
  ["front_desk", [/visiting hours/i, /heures de visite/i, /horaires de visite/i, /مواعيد الزيارة/]],
  ["verified", [/ibuprofen/i, /ibuprofène/i, /إيبوبروفين/, /الإيبوبروفين/]],
  ["streamed", [/hba1c/i, /\ba1c\b/i]],
  ["abstain", [/zorblax/i, /زوربلاكس/]],
];

export function pickScenario(message) {
  for (const [name, patterns] of KEYWORDS) {
    if (patterns.some((p) => p.test(message))) return name;
  }
  return "abstain";
}

const pick = (value, locale) => (value && typeof value === "object" && "en" in value ? value[locale] || value.en : value);
const ev = (type, payload, delayMs = 0) => ({ type, payload: { type, ...payload }, delayMs });

function contact(c, locale) {
  return { label: pick(c.label, locale), number: c.number, hours: pick(c.hours, locale) };
}

/** Split text into small chunks (about three words) so the UI receives a realistic delta stream. */
export function chunk(text, words = 3) {
  const parts = text.split(/(\s+)/);
  const out = [];
  for (let i = 0; i < parts.length; i += words * 2) out.push(parts.slice(i, i + words * 2).join(""));
  return out.filter((p) => p !== "");
}

function meta(ctx) {
  return ev("meta", { turn_id: ctx.turnId, session_id: ctx.sessionId, locale: ctx.locale, demo_mode: true, release: RELEASE });
}

function done(ctx) {
  return ev("done", { turn_id: ctx.turnId, turns_left: ctx.turnsLeft }, 30);
}

function answer(ctx, fields) {
  return ev("answer", { citations: [], replaces_stream: false, source_language_note: false, show_seek_care: false, ...fields }, 40);
}

function sourceLanguage(ctx) {
  return ctx.locale === "en" ? [] : [ev("notice", { code: "source_language", message: pick(TEXT.sourceLanguage, ctx.locale) })];
}

function safetyScenario(ctx, kind) {
  const isCrisis = kind === "self_harm";
  const text = isCrisis ? TEXT.selfHarm : TEXT.emergency;
  const contacts = isCrisis
    ? [...HOSPITAL.crisis_lines.map((c) => contact(c, ctx.locale)), contact(HOSPITAL.emergency, ctx.locale)]
    : [contact(HOSPITAL.emergency, ctx.locale), contact(HOSPITAL.main_phone, ctx.locale)];
  const title = pick(text.title, ctx.locale);
  const message = pick(text.message, ctx.locale);
  return [
    meta(ctx),
    ev("safety", { kind, template_id: `${kind}_${ctx.locale}_v1`, title, message, contacts, sticky: true }),
    answer(ctx, { text: message, intent: "symptom_info", mode: "template", verified: true }),
    ev("notice", { code: "handoff_available", message: pick(TEXT.handoff, ctx.locale) }),
    done(ctx),
  ];
}

function streamedScenario(ctx) {
  const parts = pick(TEXT.hba1c, ctx.locale);
  const deltas = parts.flatMap((part) => chunk(part)).map((text) => ev("delta", { text }, 45));
  return [
    meta(ctx),
    ev("status", { stage: "checking" }, 60),
    ev("status", { stage: "searching" }, 120),
    ev("status", { stage: "writing" }, 120),
    ...deltas,
    answer(ctx, {
      text: parts.join(""),
      citations: [CITATIONS.hba1c, CITATIONS.a1cNiddk],
      intent: "medical_info",
      mode: "streamed",
      verified: false,
      source_language_note: ctx.locale !== "en",
      show_seek_care: true,
    }),
    ...sourceLanguage(ctx),
    done(ctx),
  ];
}

function verifiedScenario(ctx) {
  return [
    meta(ctx),
    ev("status", { stage: "checking" }, 60),
    ev("status", { stage: "searching" }, 150),
    ev("status", { stage: "writing" }, 150),
    ev("status", { stage: "verifying" }, 250),
    answer(ctx, {
      text: pick(TEXT.ibuprofen, ctx.locale),
      citations: [CITATIONS.ibuprofen],
      intent: "medication",
      mode: "verified",
      verified: true,
      source_language_note: ctx.locale !== "en",
      show_seek_care: true,
    }),
    ...sourceLanguage(ctx),
    done(ctx),
  ];
}

function replacedScenario(ctx) {
  const draft = pick(TEXT.replaced.draft, ctx.locale);
  return [
    meta(ctx),
    ev("status", { stage: "writing" }, 60),
    ...chunk(draft).map((text) => ev("delta", { text }, 50)),
    answer(ctx, {
      text: pick(TEXT.replaced.final, ctx.locale),
      citations: [CITATIONS.hba1c],
      intent: "medical_info",
      mode: "streamed",
      verified: true,
      replaces_stream: true,
    }),
    done(ctx),
  ];
}

function simpleScenario(ctx, name) {
  const t = (v) => pick(v, ctx.locale);
  switch (name) {
    case "injection":
      return [meta(ctx), ev("status", { stage: "checking" }, 60), answer(ctx, { text: t(TEXT.refusal), intent: "out_of_scope", mode: "refusal", verified: true }), done(ctx)];
    case "front_desk":
      return [meta(ctx), ev("status", { stage: "checking" }, 60), answer(ctx, { text: t(TEXT.frontDesk), intent: "hospital_admin", mode: "template", verified: true }), done(ctx)];
    case "appointment":
      return [
        meta(ctx),
        ev("status", { stage: "checking" }, 60),
        answer(ctx, { text: t(TEXT.form.answer), intent: "appointment", mode: "template", verified: true }),
        ev("form", appointmentFormEvent(ctx.locale), 30),
        done(ctx),
      ];
    case "fail":
      return [
        meta(ctx),
        ev("status", { stage: "writing" }, 60),
        ...chunk(t(TEXT.slow)).map((text) => ev("delta", { text }, 50)),
        ev("error", { code: "upstream_error", message: t(TEXT.failed), retry_after_s: null }, 60),
        done(ctx),
      ];
    default:
      return [
        meta(ctx),
        ev("status", { stage: "checking" }, 60),
        ev("status", { stage: "searching" }, 120),
        answer(ctx, { text: t(TEXT.abstain), intent: "medical_info", mode: "abstain", verified: true }),
        done(ctx),
      ];
  }
}

const PRE_STREAM = {
  rate_limited: { status: 429, code: "rate_limited", retry: 4, text: TEXT.rateLimited },
  overloaded: { status: 503, code: "overloaded", retry: 3, text: TEXT.overloaded },
  unauthorized: { status: 401, code: "unauthorized", retry: null, text: { en: "Session expired.", fr: "Session expirée.", ar: "انتهت الجلسة." } },
};

/**
 * Build the script for one turn. Returns { kind: "error", status, retry, body } for pre-stream
 * failures, { kind: "slow", head, tick } for the endless slow stream, else { kind: "sse", events }.
 */
export function buildScript(name, ctx) {
  const pre = PRE_STREAM[name];
  if (pre) {
    return { kind: "error", status: pre.status, retry: pre.retry, body: { error: { code: pre.code, message: pick(pre.text, ctx.locale), retry_after_s: pre.retry } } };
  }
  if (name === "slow") {
    return { kind: "slow", head: [meta(ctx), ev("status", { stage: "writing" }, 40)], tick: (i) => ev("delta", { text: `${pick(TEXT.slow, ctx.locale)}(${i + 1}) ` }, 400) };
  }
  if (name === "self_harm" || name === "emergency") return { kind: "sse", events: safetyScenario(ctx, name) };
  if (name === "streamed") return { kind: "sse", events: streamedScenario(ctx) };
  if (name === "verified") return { kind: "sse", events: verifiedScenario(ctx) };
  if (name === "replaced") return { kind: "sse", events: replacedScenario(ctx) };
  return { kind: "sse", events: simpleScenario(ctx, name) };
}
