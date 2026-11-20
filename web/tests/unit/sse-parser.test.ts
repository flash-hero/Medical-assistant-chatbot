import { afterEach, describe, expect, it, vi } from "vitest";
import { createSseParser, MAX_EVENT_CHARS, type SseMessage, SseBufferOverflow } from "@/lib/sse/parser";
import { readSseStream, SseTimeoutError } from "@/lib/sse/stream";

function parseAll(chunks: readonly string[]): SseMessage[] {
  const parser = createSseParser();
  const out: SseMessage[] = [];
  for (const chunk of chunks) out.push(...parser.feed(chunk));
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

describe("SSE parser", () => {
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
    const parser = createSseParser();
    expect(parser.feed("event: delta\ndata: partial")).toEqual([]);
    expect(parser.feed(" text\n\n")[0]?.data).toBe("partial text");
  });

  it("keeps two parsers independent", () => {
    const a = createSseParser();
    const b = createSseParser();
    a.feed("data: from a");
    expect(b.feed("data: from b\n\n").map((m) => m.data)).toEqual(["from b"]);
    expect(a.feed("\n\n").map((m) => m.data)).toEqual(["from a"]);
  });

  it("refuses a line that grows past the limit, even when it arrives in small chunks", () => {
    expect(() => createSseParser().feed(`data: ${"x".repeat(MAX_EVENT_CHARS + 10)}`)).toThrow(SseBufferOverflow);
    const parser = createSseParser(1_000);
    expect(() => {
      for (let i = 0; i < 200; i += 1) parser.feed("data: xxxx");
    }).toThrow(SseBufferOverflow);
  });
});

describe("T6 SSE parser cost and size cap", () => {
  it("caps the whole event, not only one line: many short data lines overflow too", () => {
    const parser = createSseParser(10_000);
    const line = `data: ${"y".repeat(90)}\n`;
    expect(() => parser.feed(line.repeat(200))).toThrow(SseBufferOverflow);
  });

  it("resets the budget after each dispatched event", () => {
    const parser = createSseParser(1_000);
    const event = `data: ${"z".repeat(600)}\n\n`;
    const out: SseMessage[] = [];
    for (let i = 0; i < 20; i += 1) out.push(...parser.feed(event));
    expect(out).toHaveLength(20);
  });

  it("parses a large event delivered one character at a time in linear time", () => {
    const text = `event: answer\ndata: ${"a".repeat(150_000)}\n\n`;
    const parser = createSseParser();
    const started = performance.now();
    const out: SseMessage[] = [];
    for (const ch of text) out.push(...parser.feed(ch));
    const elapsed = performance.now() - started;
    expect(out).toHaveLength(1);
    expect(out[0]?.data.length).toBe(150_000);
    expect(elapsed).toBeLessThan(1_500);
  });

  it("parses thousands of short lines in one chunk in linear time", () => {
    const text = "data: x\n".repeat(20_000) + "\n";
    const started = performance.now();
    const out = createSseParser().feed(text);
    expect(performance.now() - started).toBeLessThan(1_500);
    expect(out[0]?.data.length).toBe(20_000 * 2 - 1);
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

describe("T10 stream liveness", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function silentAfter(first: string): { body: ReadableStream<Uint8Array>; cancelled: () => boolean; push: (text: string) => void } {
    let cancelled = false;
    let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
        c.enqueue(new TextEncoder().encode(first));
      },
      cancel() {
        cancelled = true;
      },
    });
    return { body, cancelled: () => cancelled, push: (text) => controller?.enqueue(new TextEncoder().encode(text)) };
  }

  it("aborts a stream that stays silent for the idle timeout and closes the connection", async () => {
    vi.useFakeTimers();
    const silent = silentAfter("data: hello\n\n");
    const seen: string[] = [];
    const run = (async () => {
      for await (const msg of readSseStream(silent.body, undefined, { idleTimeoutMs: 45_000 })) seen.push(msg.data);
    })();
    const outcome = expect(run).rejects.toBeInstanceOf(SseTimeoutError);
    await vi.advanceTimersByTimeAsync(45_001);
    await outcome;
    expect(seen).toEqual(["hello"]);
    expect(silent.cancelled()).toBe(true);
  });

  it("counts keep-alive comments as activity", async () => {
    vi.useFakeTimers();
    const live = silentAfter(": keep-alive\n\n");
    let finished = false;
    const run = (async () => {
      for await (const _ of readSseStream(live.body, undefined, { idleTimeoutMs: 45_000 })) void _;
      finished = true;
    })();
    const settled = run.then(
      () => null,
      (error: unknown) => error,
    );
    for (let i = 0; i < 4; i += 1) {
      await vi.advanceTimersByTimeAsync(15_000);
      live.push(": keep-alive\n\n");
    }
    expect(live.cancelled()).toBe(false);
    live.push("data: done\n\n");
    await vi.advanceTimersByTimeAsync(1);
    expect(finished).toBe(false);
    await vi.advanceTimersByTimeAsync(45_001);
    expect(await settled).toBeInstanceOf(SseTimeoutError);
  });
});
