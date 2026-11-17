import { createSseParser, type SseMessage } from "./parser";

/** The server sends a keep-alive comment every 15 s; three missed in a row means the stream is dead. */
export const STREAM_IDLE_TIMEOUT_MS = 45_000;

export class SseAbortError extends Error {
  constructor() {
    super("SSE stream aborted");
    this.name = "AbortError";
  }
}

/** No bytes at all (not even a keep-alive comment) for the idle timeout (review T10). */
export class SseTimeoutError extends Error {
  constructor() {
    super("SSE stream went silent");
    this.name = "SseTimeoutError";
  }
}

export interface ReadSseOptions {
  /** Abort when no bytes arrive for this long; 0 disables the check. */
  readonly idleTimeoutMs?: number;
}

/**
 * Iterate the SSE messages of a fetch() response body. Aborting `signal` cancels the reader,
 * which closes the HTTP connection (the server then cancels the turn upstream). So does a stream
 * that stays silent for `idleTimeoutMs`, which then throws SseTimeoutError.
 * An event left unterminated at end of stream is discarded, as the spec requires.
 */
export async function* readSseStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
  options: ReadSseOptions = {},
): AsyncGenerator<SseMessage, void, undefined> {
  const idleMs = options.idleTimeoutMs ?? STREAM_IDLE_TIMEOUT_MS;
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = createSseParser();
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => {
    reader.cancel().catch(() => undefined);
  };
  const arm = () => {
    clearTimeout(timer);
    if (idleMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        cancel();
      }, idleMs);
    }
  };
  signal?.addEventListener("abort", cancel, { once: true });
  let finished = false;
  try {
    arm();
    while (true) {
      if (signal?.aborted) throw new SseAbortError();
      const { done, value } = await reader.read();
      if (signal?.aborted) throw new SseAbortError();
      if (timedOut) throw new SseTimeoutError();
      if (done) break;
      arm(); // any bytes count, keep-alive comments included
      for (const message of parser.feed(decoder.decode(value, { stream: true }))) yield message;
    }
    finished = true;
    for (const message of parser.feed(decoder.decode())) yield message;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    // Early exit (abort, timeout, consumer break, parse error): close the connection.
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
