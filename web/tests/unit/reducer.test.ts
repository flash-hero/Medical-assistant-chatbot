import { describe, expect, it } from "vitest";
import { chatReducer, displayText, INITIAL_CHAT_STATE, type ChatState } from "@/lib/chat/reducer";
import type { AnswerEvent, ChatEvent, SafetyEvent } from "@/lib/chat/types";

const meta: ChatEvent = {
  type: "meta",
  turn_id: "srv-1",
  session_id: "sess",
  locale: "en",
  demo_mode: true,
  release: { app_version: "1", corpus_version: "c", prompt_hash: "h", models: {} },
};
const answer = (overrides: Partial<AnswerEvent> = {}): AnswerEvent => ({
  type: "answer",
  text: "Final text [1].",
  citations: [],
  intent: "medical_info",
  mode: "streamed",
  verified: true,
  replaces_stream: false,
  source_language_note: false,
  show_seek_care: false,
  language: null,
  ...overrides,
});
const safety: SafetyEvent = {
  type: "safety",
  kind: "emergency",
  template_id: "emergency.v1",
  title: "Call emergency services",
  message: "Call now.",
  contacts: [{ label: "Emergency", number: "112", hours: "" }],
  sticky: true,
  language: null,
};

function run(events: readonly ChatEvent[], start: ChatState = INITIAL_CHAT_STATE, id = "c1"): ChatState {
  let state = chatReducer(start, { type: "turn/submit", id, question: "Q?", locale: "en" });
  for (const event of events) state = chatReducer(state, { type: "turn/event", id, event });
  return state;
}

describe("chatReducer", () => {
  it("adds a pending turn on submit", () => {
    const state = chatReducer(INITIAL_CHAT_STATE, { type: "turn/submit", id: "c1", question: "Hi", locale: "fr" });
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0]).toMatchObject({ id: "c1", question: "Hi", locale: "fr", phase: "pending", streamed: "" });
  });

  it("streams deltas, then the answer confirms the text", () => {
    const state = run([meta, { type: "status", stage: "writing" }, { type: "delta", text: "Final text " }, { type: "delta", text: "[1]." }]);
    const turn = state.turns[0]!;
    expect(turn.phase).toBe("streaming");
    expect(turn.stage).toBe("writing");
    expect(displayText(turn)).toBe("Final text [1].");
    const done = run([meta, { type: "delta", text: "Final " }, answer(), { type: "done", turn_id: "srv-1", turns_left: 7 }]);
    expect(done.turns[0]).toMatchObject({ phase: "done", stage: null, serverTurnId: "srv-1" });
    expect(displayText(done.turns[0]!)).toBe("Final text [1].");
    expect(done.turnsLeft).toBe(7);
    expect(done.demoMode).toBe(true);
  });

  it("discards streamed text when the answer replaces the stream", () => {
    const state = run([meta, { type: "delta", text: "Draft that failed checks." }, answer({ text: "Safe text.", replaces_stream: true })]);
    expect(displayText(state.turns[0]!)).toBe("Safe text.");
    expect(state.turns[0]!.streamed).toBe("");
  });

  it("ignores deltas that arrive after the answer", () => {
    const state = run([meta, answer({ text: "Answer." }), { type: "delta", text: " extra" }]);
    expect(displayText(state.turns[0]!)).toBe("Answer.");
  });

  it("keeps a sticky safety banner for the session, even across turns", () => {
    const first = run([meta, safety, answer({ mode: "template" }), { type: "done", turn_id: "srv-1", turns_left: 5 }]);
    expect(first.safety.map((s) => s.kind)).toEqual(["emergency"]);
    expect(first.turns[0]!.safety.map((s) => s.kind)).toEqual(["emergency"]);
    const second = chatReducer(first, { type: "turn/submit", id: "c2", question: "next", locale: "en" });
    expect(second.safety.map((s) => s.kind)).toEqual(["emergency"]);
  });

  it("does not make a non-sticky safety event a session banner", () => {
    const state = run([meta, { ...safety, sticky: false }]);
    expect(state.safety).toEqual([]);
    expect(state.turns[0]!.safety).toHaveLength(1);
  });

  it("records notices once per code, the form, and errors", () => {
    const state = run([
      meta,
      { type: "notice", code: "degraded", message: "m1" },
      { type: "notice", code: "degraded", message: "m2" },
      {
        type: "form",
        form_id: "appointment_request",
        title: "t",
        description: "d",
        fields: [],
        submit_url: "/api/v1/appointments",
      },
      { type: "error", code: "upstream_unavailable", message: "Try later", retry_after_s: 4 },
      { type: "done", turn_id: "srv-1", turns_left: 3 },
    ]);
    const turn = state.turns[0]!;
    expect(turn.notices).toHaveLength(1);
    expect(turn.form?.form_id).toBe("appointment_request");
    expect(turn.error).toEqual({ code: "upstream_unavailable", message: "Try later", retryAfterS: 4 });
    expect(turn.phase).toBe("error");
  });

  it("handles HTTP and network errors before any event", () => {
    let state = chatReducer(INITIAL_CHAT_STATE, { type: "turn/submit", id: "c1", question: "Q", locale: "en" });
    state = chatReducer(state, { type: "turn/failed", id: "c1", error: { code: "rate_limited", message: "", retryAfterS: 7 } });
    expect(state.turns[0]).toMatchObject({ phase: "error", error: { code: "rate_limited", retryAfterS: 7 } });
  });

  it("marks a stopped turn and ignores late events for it", () => {
    let state = run([meta, { type: "delta", text: "Partial" }]);
    state = chatReducer(state, { type: "turn/stopped", id: "c1" });
    state = chatReducer(state, { type: "turn/event", id: "c1", event: { type: "delta", text: " more" } });
    expect(state.turns[0]).toMatchObject({ phase: "stopped", streamed: "Partial", stage: null });
  });

  it("treats a stream that ends without done as a network error", () => {
    let state = run([meta, { type: "delta", text: "Cut" }]);
    state = chatReducer(state, { type: "turn/ended", id: "c1" });
    expect(state.turns[0]).toMatchObject({ phase: "error", error: { code: "network" } });
    const clean = chatReducer(run([meta, answer(), { type: "done", turn_id: "srv-1", turns_left: 1 }]), { type: "turn/ended", id: "c1" });
    expect(clean.turns[0]!.phase).toBe("done");
  });

  it("stores feedback and form submission per turn", () => {
    let state = run([meta, answer(), { type: "done", turn_id: "srv-1", turns_left: 1 }]);
    state = chatReducer(state, { type: "turn/feedback", id: "c1", rating: "down" });
    state = chatReducer(state, { type: "turn/form-sent", id: "c1", requestId: "AB12", message: "Sent" });
    expect(state.turns[0]).toMatchObject({ feedback: "down", formResult: { requestId: "AB12", message: "Sent" } });
  });

  it("ignores actions for unknown turns and resets the conversation", () => {
    const state = run([meta]);
    expect(chatReducer(state, { type: "turn/event", id: "nope", event: { type: "delta", text: "x" } })).toBe(state);
    const reset = chatReducer(state, { type: "conversation/reset" });
    expect(reset).toEqual(INITIAL_CHAT_STATE);
  });

  it("never mutates the previous state", () => {
    const before = run([meta]);
    const frozen = JSON.stringify(before);
    chatReducer(before, { type: "turn/event", id: "c1", event: { type: "delta", text: "x" } });
    expect(JSON.stringify(before)).toBe(frozen);
  });

  describe("T2 several safety events in one turn", () => {
    const abuse: SafetyEvent = { ...safety, kind: "abuse_disclosure", template_id: "abuse.v1", title: "You deserve to be safe", contacts: [{ label: "Help line", number: "3919", hours: "" }] };

    it("keeps every kind, highest priority first, whatever the arrival order", () => {
      const inOrder = run([meta, safety, abuse]);
      expect(inOrder.safety.map((s) => s.kind)).toEqual(["emergency", "abuse_disclosure"]);
      const reversed = run([meta, abuse, safety]);
      expect(reversed.safety.map((s) => s.kind)).toEqual(["emergency", "abuse_disclosure"]);
      expect(reversed.turns[0]!.safety.map((s) => s.kind)).toEqual(["emergency", "abuse_disclosure"]);
    });

    it("replaces an event of the same kind with the newer one", () => {
      const state = run([meta, safety, { ...safety, template_id: "emergency.v2", title: "Newer" }]);
      expect(state.safety).toHaveLength(1);
      expect(state.safety[0]?.title).toBe("Newer");
    });
  });

  describe("T13 non-sticky safety events", () => {
    it("stay on their turn (rendered inline) but never become the session banner", () => {
      const state = run([meta, { ...safety, sticky: false }, safety]);
      expect(state.safety.map((s) => s.sticky)).toEqual([true]);
      expect(state.turns[0]!.safety.map((s) => s.sticky)).toEqual([true]);
      const onlyInline = run([meta, { ...safety, kind: "harm_to_others", sticky: false }]);
      expect(onlyInline.turns[0]!.safety.map((s) => s.kind)).toEqual(["harm_to_others"]);
      expect(onlyInline.safety).toEqual([]);
    });
  });

  describe("T15 done without an answer", () => {
    it("turns an empty turn into a no_answer error instead of a blank bubble", () => {
      const state = run([meta, { type: "status", stage: "checking" }, { type: "done", turn_id: "srv-1", turns_left: 4 }]);
      expect(state.turns[0]).toMatchObject({ phase: "error", stage: null, error: { code: "no_answer", message: "", retryAfterS: null } });
    });

    it("marks streamed text that was never confirmed as an unanswered turn too", () => {
      const state = run([meta, { type: "delta", text: "Unconfirmed." }, { type: "done", turn_id: "srv-1", turns_left: 4 }]);
      expect(state.turns[0]).toMatchObject({ phase: "error", error: { code: "no_answer" }, streamed: "Unconfirmed." });
    });

    it("keeps a server error, and accepts a form-only turn", () => {
      const failed = run([meta, { type: "error", code: "upstream_error", message: "m", retry_after_s: null }, { type: "done", turn_id: "srv-1", turns_left: 4 }]);
      expect(failed.turns[0]!.error?.code).toBe("upstream_error");
      const form = run([
        meta,
        { type: "form", form_id: "appointment_request", title: "t", description: "d", fields: [], submit_url: "/api/v1/appointments" },
        { type: "done", turn_id: "srv-1", turns_left: 4 },
      ]);
      expect(form.turns[0]!.phase).toBe("done");
    });
  });

  describe("T18 questions-left counter", () => {
    it("starts from the session, counts an admitted turn at once, then takes the server's number", () => {
      let state = chatReducer(INITIAL_CHAT_STATE, { type: "session/started", turnsLeft: 20 });
      expect(state.turnsLeft).toBe(20);
      state = run([meta], state);
      expect(state.turnsLeft).toBe(19);
      state = chatReducer(state, { type: "turn/ended", id: "c1" });
      expect(state.turnsLeft).toBe(19);
      state = run([meta, answer(), { type: "done", turn_id: "srv-2", turns_left: 12 }], state, "c2");
      expect(state.turnsLeft).toBe(12);
    });

    it("drops to zero when the server says the session is exhausted, and never below zero", () => {
      let state = chatReducer(INITIAL_CHAT_STATE, { type: "session/started", turnsLeft: 3 });
      state = chatReducer(state, { type: "turn/submit", id: "c1", question: "Q", locale: "en" });
      state = chatReducer(state, { type: "turn/failed", id: "c1", error: { code: "session_exhausted", message: "", retryAfterS: null } });
      expect(state.turnsLeft).toBe(0);
      expect(run([meta], state, "c2").turnsLeft).toBe(0);
    });

    it("leaves an unknown counter unknown until the server sends one", () => {
      expect(run([meta]).turnsLeft).toBeNull();
    });
  });
});

describe("T18 session/started", () => {
  it("only seeds an unknown counter and never overwrites the conversation's own count", () => {
    const seeded = chatReducer(INITIAL_CHAT_STATE, { type: "session/started", turnsLeft: 20 });
    const counted = chatReducer({ ...seeded, turnsLeft: 7 }, { type: "session/started", turnsLeft: 20 });
    expect(counted.turnsLeft).toBe(7);
  });
});
