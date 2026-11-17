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

const safetyPayload = {
  type: "safety",
  kind: "emergency",
  template_id: "emergency.v1",
  title: "Call now",
  message: "Call 112.",
  contacts: [{ label: "Emergency", number: "112" }],
};

function safetyOf(payload: unknown) {
  const result = parseChatEvent(msg("safety", payload));
  return result.ok && result.event.type === "safety" ? result.event : null;
}

describe("T1 language of answer and safety text", () => {
  it("reads the optional language of an answer and of a safety event", () => {
    const answer = parseChatEvent(
      msg("answer", { type: "answer", text: "Le test", intent: "medical_info", mode: "streamed", verified: true, language: "fr" }),
    );
    expect(answer.ok && answer.event.type === "answer" && answer.event.language).toBe("fr");
    expect(safetyOf({ ...safetyPayload, language: "ar" })?.language).toBe("ar");
  });

  it("treats a missing, null or unknown language as unknown instead of rejecting the event", () => {
    const base = { type: "answer", text: "x", intent: "medical_info", mode: "streamed", verified: true };
    for (const language of [undefined, null, "de", 3]) {
      const result = parseChatEvent(msg("answer", { ...base, language }));
      expect(result.ok && result.event.type === "answer" && result.event.language).toBeNull();
    }
  });
});

describe("T4 lenient safety parsing", () => {
  it("truncates over-long text instead of dropping the banner", () => {
    const event = safetyOf({ ...safetyPayload, title: "T".repeat(900), message: "M".repeat(9000), template_id: "x".repeat(400) });
    expect(event).not.toBeNull();
    expect(event?.title.length).toBe(500);
    expect(event?.message.length).toBe(4000);
    expect(event?.contacts).toEqual([{ label: "Emergency", number: "112", hours: "" }]);
  });

  it("keeps the valid contacts and survives shape drift in the others", () => {
    const event = safetyOf({
      ...safetyPayload,
      sticky: "yes",
      contacts: [{ label: "Emergency", number: "112", hours: 24 }, "112", null, { label: "Crisis", number: "3114" }],
      extra_field: { nested: true },
    });
    expect(event?.sticky).toBe(true);
    expect(event?.contacts.map((c) => c.number)).toEqual(["112", "3114"]);
    expect(event?.contacts[0]?.hours).toBe("");
    expect(safetyOf({ ...safetyPayload, contacts: "112" })?.contacts).toEqual([]);
  });

  it("falls back to an emergency banner with UI text when kind, title or message are missing", () => {
    const event = safetyOf({ type: "safety", kind: "new_future_kind" });
    expect(event).toMatchObject({ kind: "emergency", title: "", message: "", contacts: [], sticky: true, language: null });
  });

  it("still yields a fallback banner when a safety payload is not valid JSON or not an object", () => {
    for (const data of ["{broken", "[]", '"text"', "null"]) {
      const result = parseChatEvent({ event: "safety", data, id: null, retry: null });
      expect(result, data).toMatchObject({ ok: true, event: { type: "safety", kind: "emergency", title: "", message: "", sticky: true } });
    }
  });
});

describe("T11 citation dates", () => {
  it("keeps a citation whose review date is not a real calendar date, without the date", () => {
    for (const reviewed_on of ["2025-13-45", "2025-02-30", "2025-1-5", "yesterday"]) {
      const result = parseChatEvent(
        msg("answer", { type: "answer", text: "x", citations: [{ ...citation, reviewed_on }], intent: "medical_info", mode: "streamed", verified: true }),
      );
      expect(result.ok && result.event.type === "answer" && result.event.citations, reviewed_on).toEqual([
        expect.objectContaining({ n: 1, reviewed_on: null }),
      ]);
    }
  });

  it("keeps a valid date, including 29 February in a leap year", () => {
    const result = parseChatEvent(
      msg("answer", { type: "answer", text: "x", citations: [{ ...citation, reviewed_on: "2024-02-29" }], intent: "medical_info", mode: "streamed", verified: true }),
    );
    expect(result.ok && result.event.type === "answer" && result.event.citations[0]?.reviewed_on).toBe("2024-02-29");
  });
});

describe("T16 duplicate entries from server lists", () => {
  it("keeps the first citation for each number", () => {
    const result = parseChatEvent(
      msg("answer", {
        type: "answer",
        text: "x",
        citations: [citation, { ...citation, title: "Duplicate" }, { ...citation, n: 2 }],
        intent: "medical_info",
        mode: "streamed",
        verified: true,
      }),
    );
    expect(result.ok && result.event.type === "answer" && result.event.citations.map((c) => [c.n, c.title])).toEqual([
      [1, "Diabetes"],
      [2, "Diabetes"],
    ]);
  });

  it("drops repeated form fields and repeated select options", () => {
    const result = parseChatEvent(
      msg("form", {
        type: "form",
        form_id: "appointment_request",
        title: "t",
        description: "d",
        fields: [
          { name: "full_name", label: "Name", kind: "text" },
          { name: "full_name", label: "Name again", kind: "text" },
          { name: "department_id", label: "Department", kind: "select", options: ["cardiology", "cardiology", "dermatology"] },
        ],
      }),
    );
    expect(result.ok && result.event.type === "form" && result.event.fields.map((f) => [f.name, f.options])).toEqual([
      ["full_name", []],
      ["department_id", ["cardiology", "dermatology"]],
    ]);
  });
});
