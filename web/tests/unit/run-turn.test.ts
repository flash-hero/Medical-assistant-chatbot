import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { ChatAction } from "@/lib/chat/reducer";
import { runTurn } from "@/lib/chat/run-turn";

const encoder = new TextEncoder();

function streamOf(chunks: readonly string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const meta = `event: meta\ndata: {"type":"meta","turn_id":"t1","session_id":"s1","locale":"en","demo_mode":true,"release":{"app_version":"1","corpus_version":"c","prompt_hash":"p","models":{}}}\n\n`;
const delta = `event: delta\ndata: {"type":"delta","text":"Hello."}\n\n`;
const done = `event: done\ndata: {"type":"done","turn_id":"t1","turns_left":19}\n\n`;

function collect(): { actions: ChatAction[]; dispatch: (a: ChatAction) => void } {
  const actions: ChatAction[] = [];
  return { actions, dispatch: (a) => actions.push(a) };
}

const base = { token: "tok", message: "hi", locale: "en" as const, clientTurnId: "c1" };

describe("runTurn", () => {
  it("dispatches every valid event in order, skipping unknown and invalid ones", async () => {
    const { actions, dispatch } = collect();
    const open = vi.fn().mockResolvedValue(streamOf([meta, "event: future\ndata: {}\n\n", "event: delta\ndata: nope\n\n", delta, done]));
    const outcome = await runTurn({ ...base, signal: new AbortController().signal }, dispatch, open);
    expect(outcome).toBe("done");
    expect(actions.map((a) => (a.type === "turn/event" ? a.event.type : a.type))).toEqual(["meta", "delta", "done"]);
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ clientTurnId: "c1", token: "tok" }));
  });

  it("reports a stream that ends without done", async () => {
    const { actions, dispatch } = collect();
    const outcome = await runTurn({ ...base, signal: new AbortController().signal }, dispatch, vi.fn().mockResolvedValue(streamOf([meta, delta])));
    expect(outcome).toBe("ended");
    expect(actions.at(-1)).toEqual({ type: "turn/ended", id: "c1" });
  });

  it("maps a pre-stream ApiError to turn/failed with Retry-After", async () => {
    const { actions, dispatch } = collect();
    const open = vi.fn().mockRejectedValue(new ApiError("rate_limited", 429, "Slow down", 7));
    const outcome = await runTurn({ ...base, signal: new AbortController().signal }, dispatch, open);
    expect(outcome).toBe("failed");
    expect(actions).toEqual([
      { type: "turn/failed", id: "c1", error: { code: "rate_limited", message: "Slow down", retryAfterS: 7 } },
    ]);
  });

  it("maps unexpected failures to an unknown error", async () => {
    const { actions, dispatch } = collect();
    await runTurn({ ...base, signal: new AbortController().signal }, dispatch, vi.fn().mockRejectedValue(new Error("boom")));
    expect(actions).toEqual([{ type: "turn/failed", id: "c1", error: { code: "unknown", message: "", retryAfterS: null } }]);
  });

  it("treats an abort as stopped and cancels the body", async () => {
    const { actions, dispatch } = collect();
    const controller = new AbortController();
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(encoder.encode(meta));
      },
      cancel() {
        cancelled = true;
      },
    });
    const pending = runTurn({ ...base, signal: controller.signal }, (a) => {
      dispatch(a);
      if (a.type === "turn/event" && a.event.type === "meta") controller.abort();
    }, vi.fn().mockResolvedValue(body));
    await expect(pending).resolves.toBe("stopped");
    expect(cancelled).toBe(true);
    expect(actions.at(-1)).toEqual({ type: "turn/stopped", id: "c1" });
  });

  it("treats an abort before the response as stopped", async () => {
    const { actions, dispatch } = collect();
    const open = vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(runTurn({ ...base, signal: new AbortController().signal }, dispatch, open)).resolves.toBe("stopped");
    expect(actions).toEqual([{ type: "turn/stopped", id: "c1" }]);
  });
});
