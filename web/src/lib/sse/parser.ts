/**
 * Incremental Server-Sent Events parser (WHATWG HTML "event stream interpretation").
 *
 * EventSource cannot POST, so the chat client feeds this from a fetch() body. Linear in the input
 * (review T6): each chunk is scanned once from where the previous one stopped, an incomplete line is
 * kept as a list of pieces and joined once, and data lines are appended in place. The parser's state
 * is private to the object returned by `createSseParser`; nothing outside it can see or change it.
 * One event (its data plus the line being read) may not exceed `maxEventChars`: the stream is then
 * refused with SseBufferOverflow instead of freezing the tab on a runaway payload.
 */

export interface SseMessage {
  readonly event: string;
  readonly data: string;
  readonly id: string | null;
  readonly retry: number | null;
}

/** Far above any real chat event (answer text + citations is a few tens of kB). */
export const MAX_EVENT_CHARS = 256 * 1024;

export class SseBufferOverflow extends Error {
  constructor(limit: number = MAX_EVENT_CHARS) {
    super(`SSE event exceeded ${limit} characters`);
    this.name = "SseBufferOverflow";
  }
}

export interface SseParser {
  /** Feed one decoded text chunk; returns the messages it completed. */
  feed(chunk: string): SseMessage[];
}

const LINE_BREAK = /[\r\n]/g;
const DIGITS = /^\d+$/;
const BOM = 0xfeff;
const CR = 13;
const LF = 10;
const COLON = 58;
const SPACE = 32;

export function createSseParser(maxEventChars: number = MAX_EVENT_CHARS): SseParser {
  let pieces: string[] = []; // the incomplete line, in pieces
  let pieceChars = 0;
  let pendingCR = false; // the previous chunk ended in "\r": a leading "\n" belongs to it
  let started = false;
  let eventType = "";
  let dataLines: string[] = [];
  let dataChars = 0;
  let lastEventId: string | null = null;
  let retry: number | null = null;

  const guard = () => {
    if (dataChars + pieceChars > maxEventChars) throw new SseBufferOverflow(maxEventChars);
  };

  const dispatch = (out: SseMessage[]) => {
    if (dataLines.length > 0) out.push({ event: eventType || "message", data: dataLines.join("\n"), id: lastEventId, retry });
    eventType = "";
    dataLines = [];
    dataChars = 0;
  };

  const applyField = (name: string, value: string) => {
    if (name === "event") eventType = value;
    else if (name === "data") {
      dataLines.push(value);
      dataChars += value.length + 1;
      guard();
    } else if (name === "id" && !value.includes("\u0000")) lastEventId = value;
    else if (name === "retry" && DIGITS.test(value)) retry = Number.parseInt(value, 10);
    // unknown field names are ignored by the spec
  };

  const processLine = (line: string, out: SseMessage[]) => {
    if (line === "") return dispatch(out);
    if (line.charCodeAt(0) === COLON) return; // comment / keep-alive
    const colon = line.indexOf(":");
    if (colon === -1) return applyField(line, "");
    const skip = line.charCodeAt(colon + 1) === SPACE ? 2 : 1;
    applyField(line.slice(0, colon), line.slice(colon + skip));
  };

  const takeLine = (tail: string): string => {
    if (pieces.length === 0) return tail;
    const line = pieces.join("") + tail;
    pieces = [];
    pieceChars = 0;
    return line;
  };

  return {
    feed(chunk: string): SseMessage[] {
      const out: SseMessage[] = [];
      if (chunk === "") return out;
      let i = pendingCR && chunk.charCodeAt(0) === LF ? 1 : 0;
      pendingCR = false;
      if (!started && i < chunk.length) {
        started = true;
        if (chunk.charCodeAt(i) === BOM) i += 1;
      }
      LINE_BREAK.lastIndex = i;
      for (let match = LINE_BREAK.exec(chunk); match !== null; match = LINE_BREAK.exec(chunk)) {
        const end = match.index;
        processLine(takeLine(chunk.slice(i, end)), out);
        i = end + 1;
        if (chunk.charCodeAt(end) === CR) {
          if (i === chunk.length) pendingCR = true;
          else if (chunk.charCodeAt(i) === LF) i += 1;
        }
        LINE_BREAK.lastIndex = i;
      }
      if (i < chunk.length) {
        pieces.push(chunk.slice(i));
        pieceChars += chunk.length - i;
        guard();
      }
      return out;
    },
  };
}
