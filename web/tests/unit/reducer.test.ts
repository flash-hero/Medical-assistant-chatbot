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
};

function run(events: readonly ChatEvent[], start: ChatState = INITIAL_CHAT_STATE): ChatState {
  let state = chatReducer(start, { type: "turn/submit", id: "c1", question: "Q?", locale: "en" });
  for (const event of events) state = chatReducer(state, { type: "turn/event", id: "c1", event });
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
    expect(first.safety?.kind).toBe("emergency");
    expect(first.turns[0]!.safety?.kind).toBe("emergency");
    const second = chatReducer(first, { type: "turn/submit", id: "c2", question: "next", locale: "en" });
    expect(second.safety?.kind).toBe("emergency");
  });

  it("does not make a non-sticky safety event a session banner", () => {
    const state = run([meta, { ...safety, sticky: false }]);
    expect(state.safety).toBeNull();
    expect(state.turns[0]!.safety).not.toBeNull();
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
});
