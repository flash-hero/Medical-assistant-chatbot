import { openChatStream, type ChatRequest } from "@/lib/api/client";
import { ApiError, isAbortError } from "@/lib/api/errors";
import { SseBufferOverflow } from "@/lib/sse/parser";
import { readSseStream, SseTimeoutError } from "@/lib/sse/stream";
import { parseChatEvent } from "./events";
import type { ChatAction, TurnError } from "./reducer";

export type TurnOutcome = "done" | "ended" | "failed" | "stopped";

export interface TurnRequest extends ChatRequest {
  readonly signal: AbortSignal;
}

type Dispatch = (action: ChatAction) => void;
type Open = (request: ChatRequest) => Promise<ReadableStream<Uint8Array>>;

/** Only a message the server wrote for patients is forwarded, never a code like "http_502" (review T5). */
function toTurnError(error: unknown): TurnError {
  if (error instanceof ApiError) return { code: error.code, message: error.serverMessage, retryAfterS: error.retryAfterS };
  if (error instanceof SseTimeoutError) return { code: "timeout", message: "", retryAfterS: null };
  if (error instanceof SseBufferOverflow) return { code: "invalid_response", message: "", retryAfterS: null };
  return { code: "unknown", message: "", retryAfterS: null };
}

async function consume(body: ReadableStream<Uint8Array>, request: TurnRequest, dispatch: Dispatch): Promise<boolean> {
  for await (const message of readSseStream(body, request.signal)) {
    const parsed = parseChatEvent(message);
    if (!parsed.ok) continue; // unknown event types and invalid payloads are ignored
    dispatch({ type: "turn/event", id: request.clientTurnId, event: parsed.event });
    if (parsed.event.type === "done") return true; // leaving the loop closes the connection
  }
  return false;
}

/**
 * One chat turn: POST, read the SSE body, validate each event and dispatch it to the reducer.
 * Aborting `request.signal` (the Stop button) cancels the body, which closes the HTTP connection.
 */
export async function runTurn(request: TurnRequest, dispatch: Dispatch, open: Open = openChatStream): Promise<TurnOutcome> {
  const id = request.clientTurnId;
  try {
    const body = await open(request);
    const sawDone = await consume(body, request, dispatch);
    if (sawDone) return "done";
    dispatch({ type: "turn/ended", id });
    return "ended";
  } catch (error) {
    if (isAbortError(error) || request.signal.aborted) {
      dispatch({ type: "turn/stopped", id });
      return "stopped";
    }
    dispatch({ type: "turn/failed", id, error: toTurnError(error) });
    return "failed";
  }
}
