import { mergeSafety } from "./safety";
import type { AnswerEvent, ChatEvent, ChatLocale, FormEvent, NoticeEvent, SafetyEvent, Stage } from "./types";

export type TurnPhase = "pending" | "streaming" | "done" | "stopped" | "error";
export type Rating = "up" | "down";

export interface TurnError {
  /** Stable code from core/errors.py, or a client code: "network" | "unknown". */
  readonly code: string;
  /** Localised server message ("" when the client must pick its own text). */
  readonly message: string;
  readonly retryAfterS: number | null;
}

export interface Turn {
  readonly id: string; // client_turn_id
  readonly question: string;
  readonly locale: ChatLocale;
  readonly serverTurnId: string | null;
  readonly phase: TurnPhase;
  readonly stage: Stage | null;
  readonly streamed: string;
  readonly answer: AnswerEvent | null;
  /** Every safety event of this turn, one per kind, highest priority first (non-sticky ones render inline). */
  readonly safety: readonly SafetyEvent[];
  readonly notices: readonly NoticeEvent[];
  readonly form: FormEvent | null;
  readonly formResult: { readonly requestId: string; readonly message: string } | null;
  readonly error: TurnError | null;
  readonly feedback: Rating | null;
}

export interface ChatState {
  readonly turns: readonly Turn[];
  /** Sticky emergency / crisis banners, one per kind, highest priority first: they stay for the session. */
  readonly safety: readonly SafetyEvent[];
  /** Questions left: the session's count, one less as soon as a turn is admitted, then the server's number. */
  readonly turnsLeft: number | null;
  readonly demoMode: boolean | null;
  readonly sessionId: string | null;
}

export type ChatAction =
  | { readonly type: "session/started"; readonly turnsLeft: number }
  | { readonly type: "turn/submit"; readonly id: string; readonly question: string; readonly locale: ChatLocale }
  | { readonly type: "turn/event"; readonly id: string; readonly event: ChatEvent }
  | { readonly type: "turn/failed"; readonly id: string; readonly error: TurnError }
  | { readonly type: "turn/stopped"; readonly id: string }
  | { readonly type: "turn/ended"; readonly id: string }
  | { readonly type: "turn/feedback"; readonly id: string; readonly rating: Rating }
  | { readonly type: "turn/form-sent"; readonly id: string; readonly requestId: string; readonly message: string }
  | { readonly type: "conversation/reset" };

export const INITIAL_CHAT_STATE: ChatState = Object.freeze({
  turns: Object.freeze([]) as readonly Turn[],
  safety: Object.freeze([]) as readonly SafetyEvent[],
  turnsLeft: null,
  demoMode: null,
  sessionId: null,
});

const FINAL_PHASES: ReadonlySet<TurnPhase> = new Set(["done", "stopped", "error"]);

export function isTurnActive(turn: Turn): boolean {
  return !FINAL_PHASES.has(turn.phase);
}

/** What the UI shows: the confirmed answer when it exists, else the streamed text so far. */
export function displayText(turn: Turn): string {
  return turn.answer ? turn.answer.text : turn.streamed;
}

function newTurn(id: string, question: string, locale: ChatLocale): Turn {
  return {
    id,
    question,
    locale,
    serverTurnId: null,
    phase: "pending",
    stage: null,
    streamed: "",
    answer: null,
    safety: [],
    notices: [],
    form: null,
    formResult: null,
    error: null,
    feedback: null,
  };
}

function applyTurnEvent(turn: Turn, event: ChatEvent): Turn {
  switch (event.type) {
    case "meta":
      return { ...turn, serverTurnId: event.turn_id, phase: "streaming" };
    case "status":
      return turn.answer ? turn : { ...turn, stage: event.stage, phase: "streaming" };
    case "safety":
      return { ...turn, safety: mergeSafety(turn.safety, event) };
    case "delta":
      return turn.answer ? turn : { ...turn, streamed: turn.streamed + event.text, phase: "streaming" };
    case "answer":
      return { ...turn, answer: event, stage: null, streamed: event.replaces_stream ? "" : turn.streamed };
    case "notice":
      return turn.notices.some((n) => n.code === event.code) ? turn : { ...turn, notices: [...turn.notices, event] };
    case "form":
      return { ...turn, form: event };
    case "error":
      return { ...turn, stage: null, phase: "error", error: { code: event.code, message: event.message, retryAfterS: event.retry_after_s } };
    case "done":
      return finishTurn(turn);
  }
}

/** The server never answered: an error with a retry instead of an empty bubble (review T15). */
const NO_ANSWER: TurnError = { code: "no_answer", message: "", retryAfterS: null };

function finishTurn(turn: Turn): Turn {
  if (turn.error) return { ...turn, stage: null, phase: "error" };
  if (turn.answer === null && turn.form === null) return { ...turn, stage: null, phase: "error", error: NO_ANSWER };
  return { ...turn, stage: null, phase: "done" };
}

function applySessionEvent(state: ChatState, event: ChatEvent): ChatState {
  switch (event.type) {
    case "meta": {
      // The server admitted the turn, so it counts even if the stream later breaks (review T18).
      const turnsLeft = state.turnsLeft === null ? null : Math.max(0, state.turnsLeft - 1);
      return { ...state, sessionId: event.session_id, demoMode: event.demo_mode, turnsLeft };
    }
    case "safety":
      return event.sticky ? { ...state, safety: mergeSafety(state.safety, event) } : state;
    case "done":
      return { ...state, turnsLeft: event.turns_left };
    default:
      return state;
  }
}

function updateTurn(state: ChatState, id: string, update: (turn: Turn) => Turn): ChatState {
  const index = state.turns.findIndex((t) => t.id === id);
  if (index === -1) return state;
  const current = state.turns[index]!;
  const next = update(current);
  if (next === current) return state;
  return { ...state, turns: state.turns.map((t, i) => (i === index ? next : t)) };
}

function onEvent(state: ChatState, id: string, event: ChatEvent): ChatState {
  const turn = state.turns.find((t) => t.id === id);
  if (!turn || turn.phase === "stopped" || turn.phase === "done") return state;
  return applySessionEvent(updateTurn(state, id, (t) => applyTurnEvent(t, event)), event);
}

const ENDED_WITHOUT_DONE: TurnError = { code: "network", message: "", retryAfterS: null };

function onFailed(state: ChatState, id: string, error: TurnError): ChatState {
  const next = updateTurn(state, id, (t) => ({ ...t, phase: "error", stage: null, error }));
  return error.code === "session_exhausted" ? { ...next, turnsLeft: 0 } : next;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "session/started":
      // Seeds the counter; once the conversation has its own count, that one is newer.
      return state.turnsLeft === null ? { ...state, turnsLeft: action.turnsLeft } : state;
    case "turn/submit":
      return { ...state, turns: [...state.turns, newTurn(action.id, action.question, action.locale)] };
    case "turn/event":
      return onEvent(state, action.id, action.event);
    case "turn/failed":
      return onFailed(state, action.id, action.error);
    case "turn/stopped":
      return updateTurn(state, action.id, (t) => (isTurnActive(t) ? { ...t, phase: "stopped", stage: null } : t));
    case "turn/ended":
      return updateTurn(state, action.id, (t) => (isTurnActive(t) ? { ...t, phase: "error", stage: null, error: ENDED_WITHOUT_DONE } : t));
    case "turn/feedback":
      return updateTurn(state, action.id, (t) => ({ ...t, feedback: action.rating }));
    case "turn/form-sent":
      return updateTurn(state, action.id, (t) => ({ ...t, formResult: { requestId: action.requestId, message: action.message } }));
    case "conversation/reset":
      return INITIAL_CHAT_STATE;
  }
}
