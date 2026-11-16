/**
 * Incremental Server-Sent Events parser (WHATWG HTML "event stream interpretation").
 *
 * Pure and immutable: `feedSse(state, chunk)` returns a NEW state plus the messages completed by
 * the chunk. EventSource cannot POST, so the chat client feeds this from a fetch() body.
 */

export interface SseMessage {
  readonly event: string;
  readonly data: string;
  readonly id: string | null;
  readonly retry: number | null;
}

export interface SseParserState {
  /** Text after the last complete line (an incomplete line). */
  readonly buffer: string;
  /** The previous chunk ended in "\r": a leading "\n" in the next chunk belongs to it. */
  readonly pendingCR: boolean;
  readonly started: boolean;
  readonly eventType: string;
  readonly dataLines: readonly string[];
  readonly lastEventId: string | null;
  readonly retry: number | null;
}

export const INITIAL_SSE_STATE: SseParserState = Object.freeze({
  buffer: "",
  pendingCR: false,
  started: false,
  eventType: "",
  dataLines: Object.freeze([]) as readonly string[],
  lastEventId: null,
  retry: null,
});

/** One SSE line longer than this is treated as a protocol violation (memory guard). */
export const MAX_LINE_CHARS = 1_000_000;

export class SseBufferOverflow extends Error {
  constructor() {
    super(`SSE line exceeded ${MAX_LINE_CHARS} characters`);
    this.name = "SseBufferOverflow";
  }
}

export interface FeedResult {
  readonly state: SseParserState;
  readonly messages: readonly SseMessage[];
}

type EventFields = Pick<SseParserState, "eventType" | "dataLines" | "lastEventId" | "retry">;

interface LineResult {
  readonly fields: EventFields;
  readonly message: SseMessage | null;
}

const DIGITS = /^\d+$/;

function dispatch(fields: EventFields): LineResult {
  const reset: EventFields = { ...fields, eventType: "", dataLines: [] };
  if (fields.dataLines.length === 0) return { fields: reset, message: null };
  const message: SseMessage = {
    event: fields.eventType || "message",
    data: fields.dataLines.join("\n"),
    id: fields.lastEventId,
    retry: fields.retry,
  };
  return { fields: reset, message };
}

function applyField(fields: EventFields, name: string, value: string): EventFields {
  switch (name) {
    case "event":
      return { ...fields, eventType: value };
    case "data":
      return { ...fields, dataLines: [...fields.dataLines, value] };
    case "id":
      return value.includes("\u0000") ? fields : { ...fields, lastEventId: value };
    case "retry":
      return DIGITS.test(value) ? { ...fields, retry: Number.parseInt(value, 10) } : fields;
    default:
      return fields; // unknown field names are ignored by the spec
  }
}

function processLine(fields: EventFields, line: string): LineResult {
  if (line === "") return dispatch(fields);
  if (line.startsWith(":")) return { fields, message: null }; // comment / keep-alive
  const colon = line.indexOf(":");
  const name = colon === -1 ? line : line.slice(0, colon);
  let value = colon === -1 ? "" : line.slice(colon + 1);
  if (value.startsWith(" ")) value = value.slice(1);
  return { fields: applyField(fields, name, value), message: null };
}

/** Feed one decoded text chunk. Never mutates `state`. */
export function feedSse(state: SseParserState, chunk: string): FeedResult {
  if (chunk === "") return { state, messages: [] };
  let text = chunk;
  if (state.pendingCR && text.startsWith("\n")) text = text.slice(1);
  if (!state.started && text.startsWith("﻿")) text = text.slice(1);
  const started = state.started || text.length > 0;
  const input = state.buffer + text;

  let fields: EventFields = state;
  const messages: SseMessage[] = [];
  let start = 0;
  let pendingCR = false;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input.charCodeAt(i);
    if (ch !== 10 && ch !== 13) continue;
    const result = processLine(fields, input.slice(start, i));
    fields = result.fields;
    if (result.message) messages.push(result.message);
    if (ch === 13) {
      if (i + 1 < input.length) {
        if (input.charCodeAt(i + 1) === 10) i += 1;
      } else {
        pendingCR = true;
      }
    }
    start = i + 1;
  }
  const buffer = input.slice(start);
  if (buffer.length > MAX_LINE_CHARS) throw new SseBufferOverflow();

  return {
    state: {
      buffer,
      pendingCR,
      started,
      eventType: fields.eventType,
      dataLines: fields.dataLines,
      lastEventId: fields.lastEventId,
      retry: fields.retry,
    },
    messages,
  };
}
