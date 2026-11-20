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

/**
 * An absolute http(s) URL, normalised; anything else (javascript:, data:, relative) is null.
 * User info is refused: "https://trusted.org@evil.example/" shows a trusted name but opens another host.
 */
export function asHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2083) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.username === "" && url.password === "" ? url.href : null;
  } catch {
    return null;
  }
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real calendar date written YYYY-MM-DD ("2025-13-45" and "2025-02-30" are not). */
export function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** At most `max` UTF-16 units, never ending on half of a surrogate pair. */
export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const last = cut.charCodeAt(cut.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}

/** A string cut to `max` instead of rejected; null only when it is not a string. */
export function asTruncatedString(value: unknown, max: number): string | null {
  return typeof value === "string" ? truncate(value, max) : null;
}

/** The first item for each key, in order (server lists can repeat an entry; React keys must not). */
export function uniqueBy<T>(items: readonly T[], key: (item: T) => string | number): T[] {
  const seen = new Set<string | number>();
  return items.filter((item) => {
    const k = key(item);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/** Mirrors core/schemas/hospital.py `_PHONE`: digits, spaces, (), -, . with an optional leading +. */
const PHONE = /^\+?[0-9][0-9 ()\-.]{1,24}$/;

export function asPhone(value: unknown): string | null {
  return typeof value === "string" && PHONE.test(value.trim()) ? value.trim() : null;
}
