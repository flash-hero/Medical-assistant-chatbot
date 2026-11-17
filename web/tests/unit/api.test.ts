import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createSession,
  getHospital,
  openChatStream,
  parseRetryAfter,
  postAppointment,
  postFeedback,
} from "@/lib/api/client";
import { REQUEST_TIMEOUT_MS } from "@/lib/api/errors";
import { parseHospital, telHref } from "@/lib/api/hospital";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

const hospital = {
  id: "demo",
  name: "Demo Hospital",
  is_demo: true,
  address: "1 Rue de la Paix",
  main_phone: { label: "Switchboard", number: "+33 1 84 00 00 00", hours: "24/7" },
  emergency: { label: "Emergency", number: "112" },
  crisis_lines: [{ label: "Crisis line", number: "3114" }, { label: "bad", number: "call me" }],
  handoff: { label: "Front desk", number: "+33 1 84 00 00 01" },
  visiting_hours: "12:00-20:00",
  departments: [{ id: "cardiology", name: "Cardiology", location: "B2", hours: null, accepts_appointments: true }],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseRetryAfter", () => {
  it("parses integer seconds and HTTP dates, clamped", () => {
    expect(parseRetryAfter("7")).toBe(7);
    expect(parseRetryAfter("99999")).toBe(3600);
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("soon")).toBeNull();
    const inTen = new Date(Date.now() + 10_000).toUTCString();
    expect(parseRetryAfter(inTen)).toBeGreaterThanOrEqual(8);
  });
});

describe("createSession", () => {
  it("posts the locale and validates the response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(201, {
        session_token: "tok",
        session_id: "sid",
        expires_at: "2026-11-15T22:00:00Z",
        turns_left: 20,
        hospital,
        demo_mode: true,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const session = await createSession("ar");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ locale: "ar" }) }),
    );
    expect(session).toMatchObject({ token: "tok", sessionId: "sid", turnsLeft: 20, demoMode: true });
    expect(session.hospital?.crisisLines.map((c) => c.label)).toEqual(["Crisis line"]);
  });

  it("throws an ApiError from the error envelope with Retry-After", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(429, { error: { code: "rate_limited", message: "Slow down", retry_after_s: null } }, { "retry-after": "12" })),
    );
    const error = await createSession("en").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "rate_limited", status: 429, retryAfterS: 12, message: "Slow down" });
  });

  it("maps a network failure and a malformed body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(createSession("en")).rejects.toMatchObject({ code: "network" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(201, { nope: true })));
    await expect(createSession("en")).rejects.toMatchObject({ code: "invalid_response" });
  });
});

describe("getHospital", () => {
  it("requests the localised profile", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, hospital));
    vi.stubGlobal("fetch", fetchMock);
    const result = await getHospital("fr");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/hospital?locale=fr");
    expect(result).toMatchObject({ name: "Demo Hospital", handoff: { number: "+33 1 84 00 00 01" } });
    expect(result.departments[0]).toMatchObject({ id: "cardiology", acceptsAppointments: true });
  });
});

describe("openChatStream", () => {
  it("sends the bearer token and returns the body of an event stream", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetchMock);
    const stream = await openChatStream({ token: "tok", message: "hi", locale: "en", clientTurnId: "c1" });
    expect(stream).toBeInstanceOf(ReadableStream);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer tok");
    expect(new Headers(init.headers).get("accept")).toBe("text/event-stream");
    expect(JSON.parse(String(init.body))).toEqual({ message: "hi", locale: "en", client_turn_id: "c1" });
  });

  it("rejects a non-stream success and surfaces pre-stream errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, {})));
    await expect(openChatStream({ token: "t", message: "m", locale: "en", clientTurnId: "c" })).rejects.toMatchObject({ code: "invalid_response" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(503, { error: { code: "overloaded", message: "Busy", retry_after_s: 5 } }, { "retry-after": "5" })),
    );
    await expect(openChatStream({ token: "t", message: "m", locale: "en", clientTurnId: "c" })).rejects.toMatchObject({ code: "overloaded", retryAfterS: 5 });
  });

  it("propagates an abort as an AbortError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")));
    await expect(openChatStream({ token: "t", message: "m", locale: "en", clientTurnId: "c" })).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("postFeedback / postAppointment", () => {
  it("posts feedback and accepts 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await postFeedback("tok", { turn_id: "t1", rating: "down", reason: "unsafe" });
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({ turn_id: "t1", rating: "down", reason: "unsafe" });
  });

  it("posts an appointment to a safe URL only", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(201, { request_id: "AB12CD", message: "Thanks" })));
    await expect(postAppointment("tok", "/api/v1/appointments", { full_name: "x", consent: true })).resolves.toEqual({ requestId: "AB12CD", message: "Thanks" });
    await expect(postAppointment("tok", "https://evil.example/collect", { consent: true })).rejects.toMatchObject({ code: "invalid_submit_url" });
  });
});

describe("T5 error envelope", () => {
  it("keeps the envelope's message apart from the code, and has none without an envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502, headers: { "content-type": "text/html" } })));
    const bare = await createSession("en").catch((e: unknown) => e);
    expect(bare).toMatchObject({ code: "http_502", status: 502, serverMessage: "" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { error: { code: "overloaded", message: "Ausculta est occupé.", retry_after_s: 5 } })));
    const wrapped = await createSession("fr").catch((e: unknown) => e);
    expect(wrapped).toMatchObject({ code: "overloaded", serverMessage: "Ausculta est occupé." });
  });
});

describe("T10 request timeouts", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function hangingFetch() {
    return vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
  }

  it("gives up on a session request that never answers", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());
    const pending = createSession("en").catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    expect(await pending).toMatchObject({ code: "timeout", status: 0 });
  });

  it("gives up on the hospital profile and on the chat request headers too", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());
    const hospitalPending = getHospital("en").catch((e: unknown) => e);
    const chatPending = openChatStream({ token: "t", message: "m", locale: "en", clientTurnId: "c" }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await hospitalPending).toMatchObject({ code: "timeout" });
    expect(await chatPending).toMatchObject({ code: "timeout" });
  });

  it("still reports a caller's abort as an abort, not a timeout", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const controller = new AbortController();
    const pending = createSession("en", controller.signal).catch((e: unknown) => e);
    controller.abort();
    expect(await pending).toMatchObject({ name: "AbortError" });
  });
});

describe("T12 tel: links", () => {
  it("drops the trunk (0) of an international number", () => {
    expect(telHref("+33 (0)4 72 00 00 00")).toBe("tel:+33472000000");
    expect(telHref("+44 ( 0 ) 20 7946 0000")).toBe("tel:+442079460000");
  });

  it("keeps national numbers and short codes as dialled", () => {
    expect(telHref("(04) 72 00 00 00")).toBe("tel:0472000000");
    expect(telHref("112")).toBe("tel:112");
    expect(telHref("+212 5-22.00.00.00")).toBe("tel:+212522000000");
  });
});

describe("T14 appointment idempotency", () => {
  it("sends the caller's idempotency key with the request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, { request_id: "AB12CD", message: "" }));
    vi.stubGlobal("fetch", fetchMock);
    await postAppointment("tok", "/api/v1/appointments", { consent: true }, "key-123");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("idempotency-key")).toBe("key-123");
  });
});

describe("T16 hospital lists", () => {
  it("keeps one department per id", () => {
    const parsed = parseHospital({
      ...hospital,
      departments: [
        { id: "cardiology", name: "Cardiology", accepts_appointments: true },
        { id: "cardiology", name: "Cardiology again", accepts_appointments: true },
        { id: "dermatology", name: "Dermatology", accepts_appointments: true },
      ],
    });
    expect(parsed?.departments.map((d) => d.name)).toEqual(["Cardiology", "Dermatology"]);
  });
});
