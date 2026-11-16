/** Tiny runtime validators for data that crosses a trust boundary (API responses, SSE events). */

export type Json = Record<string, unknown>;

export function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asString(value: unknown, maxLength = 20_000): string | null {
  return typeof value === "string" && value.length <= maxLength ? value : null;
}

export function asBool(value: unknown, fallback?: boolean): boolean | null {
  if (typeof value === "boolean") return value;
  return value === undefined && fallback !== undefined ? fallback : null;
}

export function asInt(value: unknown, min: number, max: number): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max ? value : null;
}

export function oneOf<T extends string>(value: unknown, options: readonly T[]): T | null {
  return typeof value === "string" && (options as readonly string[]).includes(value) ? (value as T) : null;
}

export function asArray(value: unknown, fallback: readonly unknown[] = []): readonly unknown[] | null {
  if (Array.isArray(value)) return value;
  return value === undefined ? fallback : null;
}

/** An absolute http(s) URL, normalised; anything else (javascript:, data:, relative) is null. */
export function asHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2083) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** Mirrors core/schemas/hospital.py `_PHONE`: digits, spaces, (), -, . with an optional leading +. */
const PHONE = /^\+?[0-9][0-9 ()\-.]{1,24}$/;

export function asPhone(value: unknown): string | null {
  return typeof value === "string" && PHONE.test(value.trim()) ? value.trim() : null;
}
