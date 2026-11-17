/** Client-side validation for the appointment request form (the server validates again). */

import type { FormField } from "@/lib/chat/types";

export type FieldError =
  | { readonly code: "required" }
  | { readonly code: "tooLong"; readonly max: number }
  | { readonly code: "email" }
  | { readonly code: "phone" }
  | { readonly code: "date" }
  | { readonly code: "option" }
  | { readonly code: "consent" };

export type FormValues = Readonly<Record<string, string>>;
export type FormErrors = Readonly<Record<string, FieldError>>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const PHONE = /^\+?[0-9][0-9 ()\-.]{4,24}$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

function isValidDate(value: string): boolean {
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

function kindError(field: FormField, value: string): FieldError | null {
  switch (field.kind) {
    case "email":
      return EMAIL.test(value) ? null : { code: "email" };
    case "tel":
      return PHONE.test(value) ? null : { code: "phone" };
    case "date":
      return isValidDate(value) ? null : { code: "date" };
    case "select":
      return field.options.includes(value) ? null : { code: "option" };
    default:
      return null;
  }
}

export function validateField(field: FormField, raw: string): FieldError | null {
  const value = raw.trim();
  if (value === "") return field.required ? { code: "required" } : null;
  if (value.length > field.max_length) return { code: "tooLong", max: field.max_length };
  return kindError(field, value);
}

export function validateForm(fields: readonly FormField[], values: FormValues, consent: boolean): FormErrors {
  const entries = fields
    .map((field) => [field.name, validateField(field, values[field.name] ?? "")] as const)
    .filter((entry): entry is readonly [string, FieldError] => entry[1] !== null);
  const errors: Record<string, FieldError> = Object.fromEntries(entries);
  return consent ? errors : { ...errors, consent: { code: "consent" } };
}

/** Only declared fields, trimmed, empty optionals dropped; the UI-owned consent flag is appended. */
export function buildAppointmentBody(
  fields: readonly FormField[],
  values: FormValues,
  consent: boolean,
): Readonly<Record<string, string | boolean>> {
  const entries = fields
    .map((field) => [field.name, (values[field.name] ?? "").trim()] as const)
    .filter(([, value]) => value !== "");
  return { ...Object.fromEntries(entries), consent };
}
