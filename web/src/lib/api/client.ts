/**
 * Same-origin client for the Ausculta API (docs/contracts/api.md). The browser always calls `/api/v1/*`;
 * Next.js rewrites it to the API in dev, and the reverse proxy routes it in production.
 * Every response body is validated before the UI sees it.
 */

import type { ChatLocale } from "@/lib/chat/types";
import { isSafeSubmitUrl } from "@/lib/chat/events";
import { asBool, asInt, asString, isRecord } from "@/lib/validate";
import { ApiError, errorFromResponse, safeFetch } from "./errors";
import { parseHospital, type PublicHospital } from "./hospital";

export { ApiError, parseRetryAfter } from "./errors";
export type { PhoneContact, PublicDepartment, PublicHospital } from "./hospital";

const API = "/api/v1";
const JSON_HEADERS = { "content-type": "application/json", accept: "application/json" } as const;

export interface Session {
  readonly token: string;
  readonly sessionId: string;
  readonly expiresAt: string;
  readonly turnsLeft: number;
  readonly hospital: PublicHospital | null;
  readonly demoMode: boolean;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiError("invalid_response", response.status);
  }
}

async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

function bearer(token: string): Record<string, string> {
  return { ...JSON_HEADERS, authorization: `Bearer ${token}` };
}

function parseSession(raw: unknown, status: number): Session {
  if (!isRecord(raw)) throw new ApiError("invalid_response", status);
  const token = asString(raw.session_token, 4096);
  const sessionId = asString(raw.session_id, 200);
  const expiresAt = asString(raw.expires_at, 64) ?? "";
  const turnsLeft = asInt(raw.turns_left, 0, 10_000);
  const demoMode = asBool(raw.demo_mode, true);
  if (!token || !sessionId || turnsLeft === null || demoMode === null) {
    throw new ApiError("invalid_response", status);
  }
  return { token, sessionId, expiresAt, turnsLeft, hospital: parseHospital(raw.hospital), demoMode };
}

export async function createSession(locale: ChatLocale, signal?: AbortSignal): Promise<Session> {
  const response = await safeFetch(`${API}/session`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ locale }),
    cache: "no-store",
    signal,
  });
  await ensureOk(response);
  return parseSession(await readJson(response), response.status);
}

export async function getHospital(locale: ChatLocale, signal?: AbortSignal): Promise<PublicHospital> {
  const response = await safeFetch(`${API}/hospital?locale=${encodeURIComponent(locale)}`, {
    method: "GET",
    headers: { accept: "application/json" },
    cache: "no-store",
    signal,
  });
  await ensureOk(response);
  const hospital = parseHospital(await readJson(response));
  if (!hospital) throw new ApiError("invalid_response", response.status);
  return hospital;
}

export interface ChatRequest {
  readonly token: string;
  readonly message: string;
  readonly locale: ChatLocale;
  readonly clientTurnId: string;
  readonly signal?: AbortSignal;
}

/** POST /chat and return the SSE body. Pre-stream failures arrive as JSON errors (ApiError). */
export async function openChatStream(request: ChatRequest): Promise<ReadableStream<Uint8Array>> {
  const response = await safeFetch(`${API}/chat`, {
    method: "POST",
    headers: { ...bearer(request.token), accept: "text/event-stream" },
    body: JSON.stringify({ message: request.message, locale: request.locale, client_turn_id: request.clientTurnId }),
    cache: "no-store",
    signal: request.signal,
  });
  await ensureOk(response);
  const type = response.headers.get("content-type") ?? "";
  if (!type.toLowerCase().startsWith("text/event-stream") || response.body === null) {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError("invalid_response", response.status);
  }
  return response.body;
}

export type FeedbackReason = "incorrect" | "unsafe" | "unhelpful" | "other";

export interface FeedbackBody {
  readonly turn_id: string;
  readonly rating: "up" | "down";
  readonly reason?: FeedbackReason;
  readonly comment?: string;
}

export async function postFeedback(token: string, body: FeedbackBody): Promise<void> {
  const response = await safeFetch(`${API}/feedback`, {
    method: "POST",
    headers: bearer(token),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  await ensureOk(response);
}

export interface AppointmentResult {
  readonly requestId: string;
  readonly message: string;
}

/** Personal data: posted only to a same-origin API path, never sent anywhere else. */
export async function postAppointment(
  token: string,
  submitUrl: string,
  body: Readonly<Record<string, string | boolean>>,
): Promise<AppointmentResult> {
  if (!isSafeSubmitUrl(submitUrl)) throw new ApiError("invalid_submit_url", 0);
  const response = await safeFetch(submitUrl, {
    method: "POST",
    headers: bearer(token),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  await ensureOk(response);
  const raw = await readJson(response);
  const requestId = isRecord(raw) ? asString(raw.request_id, 64) : null;
  const message = isRecord(raw) ? (asString(raw.message, 2000) ?? "") : "";
  if (!requestId) throw new ApiError("invalid_response", response.status);
  return { requestId, message };
}
