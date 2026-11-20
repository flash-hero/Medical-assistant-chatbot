/**
 * Scripted chat scenarios for the mock API, chosen by keywords in the user's message (EN / FR / AR).
 * Each script is a pre-stream JSON error, a raw non-JSON response, or a list of SSE events with delays,
 * following docs/contracts/chat-events.schema.json. All content is synthetic.
 *
 * Like the real server (app/pipeline/engine.py), the answer is written in the language of the QUESTION
 * (`ctx.language`), which may differ from the UI locale (`ctx.locale`), and answer and safety events say
 * which language they are in. Deterministic safety (emergency, self-harm) and errors use the UI locale,
 * as the server's precheck and error templates do.
 */
import { CITATIONS, HOSPITAL, RELEASE } from "./fixtures.mjs";
import { appointmentFormEvent } from "./form-scenario.mjs";
import { TEXT } from "./texts.mjs";

const ABUSE = [/hits me/i, /beats me/i, /me frappe/i, /يضربني/];
const EMERGENCY = [/chest pain/i, /can'?t breathe/i, /douleur (thoracique|dans la poitrine)/i, /du mal à respirer/i, /ألم في الصدر/, /لا أستطيع التنفس/];

/** Order matters: safety scenarios are checked first, exactly like the real pipeline. */
const KEYWORDS = [
  ["self_harm", [/kill myself/i, /end my life/i, /suicid/i, /me tuer/i, /mettre fin à mes jours/i, /انتحار/, /أنهي حياتي/, /أقتل نفسي/]],
  ["safety_drift", [/overdose/i, /surdose/i, /جرعة زائدة/]],
  ["emergency", EMERGENCY],
  ["injection", [/ignore (all|previous|the) (previous )?instructions/i, /system prompt/i, /ignore(z)? (les|toutes les) instructions/i, /تجاهل التعليمات/]],
  ["rate_limited", [/\b429\b/, /rate limit/i]],
  ["overloaded", [/\b503\b/, /overload/i, /surcharg/i, /ضغط كبير/]],
  ["bad_gateway", [/\b502\b/]],
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
  // Abuse disclosed together with an emergency: two safety events in one turn (review T2).
  if (ABUSE.some((p) => p.test(message))) return EMERGENCY.some((p) => p.test(message)) ? "emergency_abuse" : "abuse";
  for (const [name, patterns] of KEYWORDS) {
    if (patterns.some((p) => p.test(message))) return name;
  }
  return "abstain";
}

const ARABIC = /[؀-ۿ]/g;
const LATIN = /[A-Za-zÀ-ÿ]/g;
const FRENCH = /\b(le|la|les|des|du|de|une|un|et|est|que|quelles?|quels?|je|vous|mon|ma|mes|dans|pour|avec|sont|sert|puis|quoi)\b|\b[ldjnsc]['’]|[àâçéèêëîïôûùœ]/gi;
const ENGLISH = /\b(the|what|how|is|are|can|does|do|my|i|you|your|with|for|and|to|please|give|this|will|would|have|has|an)\b/gi;

/** The language of a question, as the server's classifier would judge it; null when unclear. */
export function detectLanguage(message) {
  const arabic = message.match(ARABIC)?.length ?? 0;
  const latin = message.match(LATIN)?.length ?? 0;
  if (arabic === 0 && latin === 0) return null;
  if (arabic > latin) return "ar";
  const french = message.match(FRENCH)?.length ?? 0;
  const english = message.match(ENGLISH)?.length ?? 0;
  if (french > english) return "fr";
  return english > french ? "en" : null;
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

/** An answer in `language` (default: the question's), with the server's source-language flag. */
function answer(ctx, fields, language = ctx.language) {
  const citations = fields.citations ?? [];
  return ev(
    "answer",
    {
      citations,
      replaces_stream: false,
      source_language_note: citations.some((c) => c.language !== language),
      show_seek_care: false,
      language,
      ...fields,
    },
    40,
  );
}

/** The server's notice when a cited source is in another language than the answer (before the answer). */
function sourceLanguageNotice(ctx, citations) {
  return citations.some((c) => c.language !== ctx.language)
    ? [ev("notice", { code: "source_language", message: pick(TEXT.sourceLanguage, ctx.language) })]
    : [];
}

const SAFETY_TEXT = { emergency: TEXT.emergency, self_harm: TEXT.selfHarm, abuse_disclosure: TEXT.abuse };

function safetyContacts(kind, locale) {
  if (kind === "self_harm") return [...HOSPITAL.crisis_lines.map((c) => contact(c, locale)), contact(HOSPITAL.emergency, locale)];
  if (kind === "abuse_disclosure") return [contact(HOSPITAL.handoff, locale), contact(HOSPITAL.emergency, locale)];
  return [contact(HOSPITAL.emergency, locale), contact(HOSPITAL.main_phone, locale)];
}

function safetyEvent(kind, language) {
  const text = SAFETY_TEXT[kind];
  return ev("safety", {
    kind,
    template_id: `${kind}_${language}_v1`,
    title: pick(text.title, language),
    message: pick(text.message, language),
    contacts: safetyContacts(kind, language),
    sticky: true,
    language,
  });
}

/**
 * Safety turns. Emergency and self-harm come from the deterministic precheck, in the UI locale; an abuse
 * disclosure is found after routing, in the question's language (app/pipeline/engine.py `_body`,
 * `_after_route`). Several kinds in one turn arrive in SAFETY_ORDER, emergency first.
 */
function safetyScenario(ctx, kinds) {
  const first = kinds[0];
  const firstLanguage = first === "abuse_disclosure" ? ctx.language : ctx.locale;
  return [
    meta(ctx),
    ...kinds.map((kind) => safetyEvent(kind, kind === "abuse_disclosure" ? ctx.language : ctx.locale)),
    answer(ctx, { text: pick(SAFETY_TEXT[first].message, firstLanguage), intent: "symptom_info", mode: "template", verified: true }, firstLanguage),
    ev("notice", { code: "handoff_available", message: pick(TEXT.handoff, firstLanguage) }),
    done(ctx),
  ];
}

/**
 * Contract drift (review T4, T11): a safety event a strict parser rejects (over-long template id, string
 * `sticky`, a broken contact, an unknown field) and a citation with an impossible review date.
 */
function driftScenario(ctx) {
  const t = (v) => pick(v, ctx.locale);
  return [
    meta(ctx),
    ev("safety", {
      kind: "emergency",
      template_id: `emergency.${"x".repeat(240)}`,
      title: t(TEXT.emergency.title),
      message: t(TEXT.emergency.message),
      contacts: [contact(HOSPITAL.emergency, ctx.locale), { label: "Broken", number: "call us" }, "112"],
      sticky: "yes",
      language: ctx.locale,
      severity: "high",
    }),
    answer(
      ctx,
      {
        text: `${t(TEXT.emergency.message)} [1]`,
        citations: [{ ...CITATIONS.hba1c, reviewed_on: "2025-13-45" }],
        intent: "symptom_info",
        mode: "template",
        verified: true,
      },
      ctx.locale,
    ),
    done(ctx),
  ];
}

function streamedScenario(ctx) {
  const parts = pick(TEXT.hba1c, ctx.language);
  const citations = [CITATIONS.hba1c, CITATIONS.a1cNiddk];
  const deltas = parts.flatMap((part) => chunk(part)).map((text) => ev("delta", { text }, 45));
  return [
    meta(ctx),
    ev("status", { stage: "checking" }, 60),
    ev("status", { stage: "searching" }, 120),
    ev("status", { stage: "writing" }, 120),
    ...deltas,
    ...sourceLanguageNotice(ctx, citations),
    answer(ctx, { text: parts.join(""), citations, intent: "medical_info", mode: "streamed", verified: false, show_seek_care: true }),
    done(ctx),
  ];
}

function verifiedScenario(ctx) {
  const citations = [CITATIONS.ibuprofen, CITATIONS.ibuprofenFr];
  return [
    meta(ctx),
    ev("status", { stage: "checking" }, 60),
    ev("status", { stage: "searching" }, 150),
    ev("status", { stage: "writing" }, 150),
    ev("status", { stage: "verifying" }, 250),
    ...sourceLanguageNotice(ctx, citations),
    answer(ctx, { text: pick(TEXT.ibuprofen, ctx.language), citations, intent: "medication", mode: "verified", verified: true, show_seek_care: true }),
    done(ctx),
  ];
}

function replacedScenario(ctx) {
  const draft = pick(TEXT.replaced.draft, ctx.language);
  return [
    meta(ctx),
    ev("status", { stage: "writing" }, 60),
    ...chunk(draft).map((text) => ev("delta", { text }, 50)),
    answer(ctx, {
      text: pick(TEXT.replaced.final, ctx.language),
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
  const t = (v) => pick(v, ctx.language);
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
        ev("form", appointmentFormEvent(ctx.language), 30),
        done(ctx),
      ];
    case "fail":
      return [
        meta(ctx),
        ev("status", { stage: "writing" }, 60),
        ...chunk(t(TEXT.slow)).map((text) => ev("delta", { text }, 50)),
        ev("error", { code: "upstream_error", message: pick(TEXT.failed, ctx.locale), retry_after_s: null }, 60),
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

const SAFETY_SCENARIOS = {
  self_harm: ["self_harm"],
  emergency: ["emergency"],
  abuse: ["abuse_disclosure"],
  emergency_abuse: ["emergency", "abuse_disclosure"],
};

/**
 * Build the script for one turn. `ctx.locale` is the UI locale, `ctx.language` the question's language
 * (defaults to the locale). Returns { kind: "error", status, retry, body } for pre-stream failures,
 * { kind: "raw", status, contentType, body } for a non-JSON proxy error, { kind: "slow", head, tick }
 * for the endless slow stream, else { kind: "sse", events }.
 */
export function buildScript(name, rawCtx) {
  const ctx = { ...rawCtx, language: rawCtx.language ?? rawCtx.locale };
  const pre = PRE_STREAM[name];
  if (pre) {
    return { kind: "error", status: pre.status, retry: pre.retry, body: { error: { code: pre.code, message: pick(pre.text, ctx.locale), retry_after_s: pre.retry } } };
  }
  if (name === "bad_gateway") return { kind: "raw", status: 502, contentType: "text/html; charset=utf-8", body: TEXT.gatewayPage };
  if (name === "slow") {
    return { kind: "slow", head: [meta(ctx), ev("status", { stage: "writing" }, 40)], tick: (i) => ev("delta", { text: `${pick(TEXT.slow, ctx.language)}(${i + 1}) ` }, 400) };
  }
  if (SAFETY_SCENARIOS[name]) return { kind: "sse", events: safetyScenario(ctx, SAFETY_SCENARIOS[name]) };
  if (name === "safety_drift") return { kind: "sse", events: driftScenario(ctx) };
  if (name === "streamed") return { kind: "sse", events: streamedScenario(ctx) };
  if (name === "verified") return { kind: "sse", events: verifiedScenario(ctx) };
  if (name === "replaced") return { kind: "sse", events: replacedScenario(ctx) };
  return { kind: "sse", events: simpleScenario(ctx, name) };
}
