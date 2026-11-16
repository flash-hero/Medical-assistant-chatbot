import { describe, expect, it } from "vitest";
import { feedSse, INITIAL_SSE_STATE, type SseMessage, SseBufferOverflow } from "@/lib/sse/parser";
import { readSseStream } from "@/lib/sse/stream";

function parseAll(chunks: readonly string[]): SseMessage[] {
  let state = INITIAL_SSE_STATE;
  const out: SseMessage[] = [];
  for (const chunk of chunks) {
    const result = feedSse(state, chunk);
    state = result.state;
    out.push(...result.messages);
  }
  return out;
}

function streamOf(parts: readonly (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(typeof part === "string" ? encoder.encode(part) : part);
      controller.close();
    },
  });
}

describe("feedSse", () => {
  it("parses a single event with a type and JSON data", () => {
    const [msg] = parseAll(['event: delta\ndata: {"type":"delta","text":"Hi"}\n\n']);
    expect(msg).toEqual({ event: "delta", data: '{"type":"delta","text":"Hi"}', id: null, retry: null });
  });

  it("defaults the event type to message", () => {
    const [msg] = parseAll(["data: hello\n\n"]);
    expect(msg?.event).toBe("message");
  });

  it("reassembles an event split mid-field across many chunks", () => {
    const text = 'event: answer\ndata: {"type":"answer","text":"A long answer"}\n\n';
    const chunks = text.split("");
    const messages = parseAll(chunks);
    expect(messages).toHaveLength(1);
    expect(messages[0]?.event).toBe("answer");
    expect(JSON.parse(messages[0]?.data ?? "{}")).toEqual({ type: "answer", text: "A long answer" });
  });

  it("splits several events delivered in one chunk", () => {
    const messages = parseAll(["event: status\ndata: 1\n\nevent: status\ndata: 2\n\nevent: done\ndata: 3\n\n"]);
    expect(messages.map((m) => m.data)).toEqual(["1", "2", "3"]);
  });

  it("joins multi-line data with newlines", () => {
    const [msg] = parseAll(["data: line one\ndata: line two\ndata:\ndata: line four\n\n"]);
    expect(msg?.data).toBe("line one\nline two\n\nline four");
  });

  it("ignores keep-alive comments, including inside an event", () => {
    const messages = parseAll([": keep-alive\n\n", "event: delta\n: ping\ndata: x\n\n", ":\n\n"]);
    expect(messages).toEqual([{ event: "delta", data: "x", id: null, retry: null }]);
  });

  it("handles CRLF and lone CR line endings, including a CRLF split across chunks", () => {
    const messages = parseAll(["event: a\r", "\ndata: 1\r\n\r", "\nevent: b\rdata: 2\r\r"]);
    expect(messages.map((m) => [m.event, m.data])).toEqual([
      ["a", "1"],
      ["b", "2"],
    ]);
  });

  it("strips exactly one space after the colon and keeps the rest", () => {
    const [msg] = parseAll(["data:  two spaces\n\n"]);
    expect(msg?.data).toBe(" two spaces");
  });

  it("treats a field without a colon as a field with an empty value", () => {
    const [msg] = parseAll(["data\ndata: x\n\n"]);
    expect(msg?.data).toBe("\nx");
  });

  it("does not dispatch an event that has no data lines", () => {
    expect(parseAll(["event: status\n\n"])).toEqual([]);
  });

  it("resets the event type after each dispatch", () => {
    const messages = parseAll(["event: meta\ndata: 1\n\ndata: 2\n\n"]);
    expect(messages.map((m) => m.event)).toEqual(["meta", "message"]);
  });

  it("tracks id and retry fields, ignoring NUL ids and non-numeric retry values", () => {
    const messages = parseAll(["id: 7\nretry: 1500\ndata: a\n\n", "id: bad\u0000id\nretry: soon\ndata: b\n\n"]);
    expect(messages[0]).toMatchObject({ id: "7", retry: 1500 });
    // Both values persist for the stream; the invalid updates are ignored.
    expect(messages[1]).toMatchObject({ id: "7", retry: 1500 });
  });

  it("ignores unknown fields", () => {
    const [msg] = parseAll(["foo: bar\ndata: ok\n\n"]);
    expect(msg?.data).toBe("ok");
  });

  it("strips a leading byte order mark once", () => {
    const [msg] = parseAll(["﻿data: x\n\n"]);
    expect(msg?.data).toBe("x");
  });

  it("keeps an incomplete trailing event buffered", () => {
    const first = feedSse(INITIAL_SSE_STATE, "event: delta\ndata: partial");
    expect(first.messages).toEqual([]);
    const second = feedSse(first.state, " text\n\n");
    expect(second.messages[0]?.data).toBe("partial text");
  });

  it("does not mutate the previous state", () => {
    const before = INITIAL_SSE_STATE;
    const snapshot = JSON.stringify(before);
    feedSse(before, "data: x\n");
    expect(JSON.stringify(before)).toBe(snapshot);
  });

  it("refuses a line that grows past the buffer limit", () => {
    expect(() => feedSse(INITIAL_SSE_STATE, `data: ${"x".repeat(2_000_000)}`)).toThrow(SseBufferOverflow);
  });
});

describe("readSseStream", () => {
  it("decodes UTF-8 split across byte chunks (Arabic and accents)", async () => {
    const payload = 'event: delta\ndata: {"text":"مرحبا éàü"}\n\n';
    const bytes = new TextEncoder().encode(payload);
    const parts = Array.from(bytes, (b) => new Uint8Array([b]));
    const out: SseMessage[] = [];
    for await (const msg of readSseStream(streamOf(parts))) out.push(msg);
    expect(JSON.parse(out[0]?.data ?? "{}").text).toBe("مرحبا éàü");
  });

  it("discards an unterminated event at end of stream", async () => {
    const out: SseMessage[] = [];
    for await (const msg of readSseStream(streamOf(["data: done\n\n", "data: cut off"]))) out.push(msg);
    expect(out.map((m) => m.data)).toEqual(["done"]);
  });

  it("stops and releases the reader when the signal aborts", async () => {
    const controller = new AbortController();
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      pull(c) {
        c.enqueue(new TextEncoder().encode("data: tick\n\n"));
      },
      cancel() {
        cancelled = true;
      },
    });
    const seen: string[] = [];
    await expect(
      (async () => {
        for await (const msg of readSseStream(body, controller.signal)) {
          seen.push(msg.data);
          if (seen.length === 3) controller.abort();
        }
      })(),
    ).rejects.toThrow(/abort/i);
    expect(seen).toHaveLength(3);
    expect(cancelled).toBe(true);
  });
});
