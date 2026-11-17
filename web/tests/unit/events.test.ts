import { describe, expect, it } from "vitest";
import { parseChatEvent } from "@/lib/chat/events";
import type { SseMessage } from "@/lib/sse/parser";

function msg(event: string, payload: unknown): SseMessage {
  return { event, data: JSON.stringify(payload), id: null, retry: null };
}

const citation = {
  n: 1,
  title: "Diabetes",
  publisher: "MedlinePlus",
  url: "https://medlineplus.gov/diabetes.html",
  heading: "Symptoms",
  reviewed_on: "2025-05-01",
  language: "en",
  snippet: "Diabetes is a disease in which your blood glucose is too high.",
};

describe("parseChatEvent", () => {
  it("parses a meta event", () => {
    const result = parseChatEvent(
      msg("meta", {
        type: "meta",
        turn_id: "t1",
        session_id: "s1",
        locale: "fr",
        demo_mode: true,
        release: { app_version: "0.1", corpus_version: "c1", prompt_hash: "h", models: { answer: "m" } },
      }),
    );
    expect(result).toMatchObject({ ok: true, event: { type: "meta", locale: "fr", demo_mode: true } });
  });

  it("parses each status stage and rejects unknown stages", () => {
    for (const stage of ["checking", "searching", "writing", "verifying"]) {
      expect(parseChatEvent(msg("status", { type: "status", stage })).ok).toBe(true);
    }
    expect(parseChatEvent(msg("status", { type: "status", stage: "dreaming" })).ok).toBe(false);
  });

  it("parses a safety event with defaults", () => {
    const result = parseChatEvent(
      msg("safety", {
        type: "safety",
        kind: "emergency",
        template_id: "emergency.v1",
        title: "Call now",
        message: "Call 112.",
        contacts: [{ label: "Emergency", number: "112" }],
      }),
    );
    expect(result.ok && result.event.type === "safety" && result.event).toMatchObject({
      sticky: true,
      contacts: [{ label: "Emergency", number: "112", hours: "" }],
    });
  });

  it("drops safety contacts whose number is not dialable", () => {
    const result = parseChatEvent(
      msg("safety", {
        type: "safety",
        kind: "self_harm",
        template_id: "self_harm.v1",
        title: "t",
        message: "m",
        contacts: [
          { label: "ok", number: "+33 1 23 45 67 89" },
          { label: "bad", number: "javascript:alert(1)" },
        ],
      }),
    );
    expect(result.ok && result.event.type === "safety" && result.event.contacts.map((c) => c.label)).toEqual(["ok"]);
  });

  it("parses an answer with citations and fills optional flags", () => {
    const result = parseChatEvent(
      msg("answer", { type: "answer", text: "Hi [1]", citations: [citation], intent: "medical_info", mode: "streamed", verified: true }),
    );
    expect(result.ok && result.event).toMatchObject({
      type: "answer",
      replaces_stream: false,
      source_language_note: false,
      show_seek_care: false,
      citations: [{ n: 1, url: "https://medlineplus.gov/diabetes.html" }],
    });
  });

  it("drops citations with a non-http(s) url but keeps the answer", () => {
    const result = parseChatEvent(
      msg("answer", {
        type: "answer",
        text: "x",
        citations: [
          { ...citation, url: "javascript:alert(1)" },
          { ...citation, n: 2, url: "data:text/html,boom" },
          { ...citation, n: 3 },
        ],
        intent: "medical_info",
        mode: "verified",
        verified: true,
      }),
    );
    expect(result.ok && result.event.type === "answer" && result.event.citations.map((c) => c.n)).toEqual([3]);
  });

  it("truncates an over-long snippet instead of rejecting the citation", () => {
    const result = parseChatEvent(
      msg("answer", {
        type: "answer",
        text: "x",
        citations: [{ ...citation, snippet: "y".repeat(900) }],
        intent: "medical_info",
        mode: "streamed",
        verified: false,
      }),
    );
    expect(result.ok && result.event.type === "answer" && result.event.citations[0]?.snippet.length).toBe(600);
  });

  it("rejects an answer with an unknown mode", () => {
    expect(parseChatEvent(msg("answer", { type: "answer", text: "x", intent: "medical_info", mode: "freestyle", verified: true })).ok).toBe(false);
  });

  it("parses notice, delta, error and done events", () => {
    expect(parseChatEvent(msg("notice", { type: "notice", code: "degraded", message: "m" })).ok).toBe(true);
    expect(parseChatEvent(msg("delta", { type: "delta", text: "Hello. " })).ok).toBe(true);
    const err = parseChatEvent(msg("error", { type: "error", code: "upstream_unavailable", message: "m", retry_after_s: 4.5 }));
    expect(err.ok && err.event).toMatchObject({ retry_after_s: 4.5 });
    const done = parseChatEvent(msg("done", { type: "done", turn_id: "t", turns_left: 3 }));
    expect(done.ok && done.event).toMatchObject({ turns_left: 3 });
  });

  it("clamps an absurd retry_after_s", () => {
    const err = parseChatEvent(msg("error", { type: "error", code: "x", message: "m", retry_after_s: 1e9 }));
    expect(err.ok && err.event.type === "error" && err.event.retry_after_s).toBe(3600);
  });

  it("parses a form event and rejects an off-origin submit_url", () => {
    const form = {
      type: "form",
      form_id: "appointment_request",
      title: "Request",
      description: "d",
      fields: [{ name: "full_name", label: "Name", kind: "text", required: true }],
    };
    const ok = parseChatEvent(msg("form", form));
    expect(ok.ok && ok.event).toMatchObject({ submit_url: "/api/v1/appointments", fields: [{ max_length: 200, options: [] }] });
    for (const submit_url of ["https://evil.example/x", "//evil.example/api/v1/a", "/api/v1/../../x", "/other"]) {
      expect(parseChatEvent(msg("form", { ...form, submit_url })).ok).toBe(false);
    }
  });

  it("rejects a form field with an unsafe name or kind", () => {
    const base = { type: "form", form_id: "appointment_request", title: "t", description: "d" };
    expect(parseChatEvent(msg("form", { ...base, fields: [{ name: "__proto__", label: "x", kind: "text" }] })).ok).toBe(false);
    expect(parseChatEvent(msg("form", { ...base, fields: [{ name: "x", label: "x", kind: "file" }] })).ok).toBe(false);
  });

  it("ignores unknown event types and mismatched type fields", () => {
    expect(parseChatEvent(msg("x-future", { type: "x-future" }))).toEqual({ ok: false, reason: "unknown_event" });
    expect(parseChatEvent(msg("delta", { type: "answer", text: "x" })).ok).toBe(false);
  });

  it("rejects invalid JSON and non-object payloads", () => {
    expect(parseChatEvent({ event: "delta", data: "{not json", id: null, retry: null })).toEqual({ ok: false, reason: "invalid_json" });
    expect(parseChatEvent({ event: "delta", data: "[]", id: null, retry: null }).ok).toBe(false);
  });
});
