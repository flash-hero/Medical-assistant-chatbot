import { feedSse, INITIAL_SSE_STATE, type SseMessage } from "./parser";

export class SseAbortError extends Error {
  constructor() {
    super("SSE stream aborted");
    this.name = "AbortError";
  }
}

/**
 * Iterate the SSE messages of a fetch() response body. Aborting `signal` cancels the reader,
 * which closes the HTTP connection (the server then cancels the turn upstream).
 * An event left unterminated at end of stream is discarded, as the spec requires.
 */
export async function* readSseStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage, void, undefined> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let state = INITIAL_SSE_STATE;
  const onAbort = () => {
    reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", onAbort, { once: true });
  let finished = false;
  try {
    while (true) {
      if (signal?.aborted) throw new SseAbortError();
      const { done, value } = await reader.read();
      if (signal?.aborted) throw new SseAbortError();
      if (done) break;
      const result = feedSse(state, decoder.decode(value, { stream: true }));
      state = result.state;
      for (const message of result.messages) yield message;
    }
    finished = true;
    const tail = feedSse(state, decoder.decode());
    for (const message of tail.messages) yield message;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    // Early exit (abort, consumer break, parse error): close the connection.
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
