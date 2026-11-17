/**
 * Screen-reader announcements for streamed answers: whole sentences only, at most once per interval,
 * so assistive technology is not flooded with one update per token.
 */

const CITATIONS = /\s*\[\d{1,3}(?:\s*,\s*\d{1,3})*\]/g;
const LIST_MARKER = /^\s*[-•]\s+/;
/** A sentence ends with . ! ? or the Arabic question mark, followed by whitespace or the end of the text. */
const SENTENCE_END = /[.!?؟…](?=\s|$)/g;

export function toPlainText(markdown: string): string {
  return markdown
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(LIST_MARKER, "").trim())
    .filter((line) => line !== "")
    .join(" ")
    .replace(/\*\*/g, "")
    .replace(CITATIONS, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export interface SentenceSlice {
  readonly text: string;
  readonly end: number;
}

/** The complete sentences of `text` after `cursor`, and the index where they end. */
export function completedSentences(text: string, cursor: number): SentenceSlice {
  let end = cursor;
  SENTENCE_END.lastIndex = cursor;
  for (let match = SENTENCE_END.exec(text); match !== null; match = SENTENCE_END.exec(text)) {
    end = match.index + match[0].length;
  }
  return { text: text.slice(cursor, end).trim(), end };
}

export interface Announcer {
  /** The full streamed text so far (it only grows). */
  stream(text: string): void;
  /** The confirmed answer: announce whatever has not been announced yet, immediately. */
  finish(text: string): void;
  /** The confirmed answer replaces the streamed draft: announce it in full. */
  replace(text: string): void;
  reset(): void;
  dispose(): void;
}

export function createAnnouncer(emit: (text: string) => void, intervalMs = 2500): Announcer {
  let cursor = 0;
  let latest = "";
  let lastEmit = Number.NEGATIVE_INFINITY;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const clearTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const say = (text: string) => {
    if (text === "") return;
    lastEmit = Date.now();
    emit(text);
  };
  const flushSentences = () => {
    timer = null;
    const slice = completedSentences(latest, cursor);
    cursor = slice.end;
    say(slice.text);
  };

  return {
    stream(text) {
      latest = toPlainText(text);
      if (timer !== null) return;
      const wait = lastEmit + intervalMs - Date.now();
      if (wait <= 0) flushSentences();
      else timer = setTimeout(flushSentences, wait);
    },
    finish(text) {
      clearTimer();
      latest = toPlainText(text);
      const rest = latest.slice(cursor).trim();
      cursor = latest.length;
      say(rest);
    },
    replace(text) {
      clearTimer();
      latest = toPlainText(text);
      cursor = latest.length;
      say(latest);
    },
    reset() {
      clearTimer();
      cursor = 0;
      latest = "";
      lastEmit = Number.NEGATIVE_INFINITY;
    },
    dispose() {
      clearTimer();
    },
  };
}
