/** Error envelope handling for the HTTP API contract (docs/contracts/api.md). */

import { asString, isRecord } from "@/lib/validate";

export const MAX_RETRY_AFTER_S = 3600;

/** Client-side codes, alongside the stable server codes from core/errors.py. */
export type ClientErrorCode = "network" | "invalid_response" | "invalid_submit_url";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryAfterS: number | null;

  constructor(code: string, status: number, message = "", retryAfterS: number | null = null) {
    super(message || code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.retryAfterS = retryAfterS;
  }
}

function clampRetry(seconds: number): number {
  return Math.min(Math.max(0, Math.ceil(seconds)), MAX_RETRY_AFTER_S);
}

/** `Retry-After` is either delta-seconds or an HTTP date. Anything else is ignored. */
export function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const value = header.trim();
  if (/^\d+$/.test(value)) return clampRetry(Number.parseInt(value, 10));
  const at = Date.parse(value);
  if (Number.isNaN(at)) return null;
  return clampRetry((at - Date.now()) / 1000);
}

function envelopeRetry(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? clampRetry(raw) : null;
}

/** Build an ApiError from a non-2xx response, reading the `{"error": {...}}` envelope when present. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  const headerRetry = parseRetryAfter(response.headers.get("retry-after"));
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const envelope = isRecord(body) && isRecord(body.error) ? body.error : null;
  const code = (envelope && asString(envelope.code, 100)) || `http_${response.status}`;
  const message = (envelope && asString(envelope.message, 2000)) || "";
  const retry = (envelope && envelopeRetry(envelope.retry_after_s)) ?? headerRetry;
  return new ApiError(code, response.status, message, retry);
}

/** DOMException is not an Error subclass in every runtime, so match on the name. */
export function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

/** fetch() wrapper: network failures become ApiError("network"); aborts propagate unchanged. */
export async function safeFetch(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError("network", 0);
  }
}
