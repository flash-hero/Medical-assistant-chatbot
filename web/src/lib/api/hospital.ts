/** PublicHospital (GET /api/v1/hospital, and embedded in the session response), validated. */

import { asBool, asPhone, asString, isRecord, uniqueBy } from "@/lib/validate";

export interface PhoneContact {
  readonly label: string;
  readonly number: string;
  readonly hours: string;
}

export interface PublicDepartment {
  readonly id: string;
  readonly name: string;
  readonly location: string;
  readonly hours: string;
  readonly acceptsAppointments: boolean;
}

export interface PublicHospital {
  readonly id: string;
  readonly name: string;
  readonly isDemo: boolean;
  readonly address: string;
  readonly mainPhone: PhoneContact | null;
  readonly emergency: PhoneContact | null;
  readonly crisisLines: readonly PhoneContact[];
  readonly handoff: PhoneContact | null;
  readonly visitingHours: string;
  readonly departments: readonly PublicDepartment[];
}

const MAX_DEPARTMENTS = 100;
const MAX_CRISIS_LINES = 10;

function optionalText(value: unknown, max = 500): string {
  return asString(value, max) ?? "";
}

export function parseContact(raw: unknown): PhoneContact | null {
  if (!isRecord(raw)) return null;
  const label = asString(raw.label, 200);
  const number = asPhone(raw.number);
  if (label === null || number === null) return null;
  return { label, number, hours: optionalText(raw.hours, 200) };
}

function parseDepartment(raw: unknown): PublicDepartment | null {
  if (!isRecord(raw)) return null;
  const id = asString(raw.id, 64);
  const name = asString(raw.name, 200);
  if (id === null || !/^[a-z0-9_]+$/.test(id) || name === null) return null;
  return {
    id,
    name,
    location: optionalText(raw.location, 200),
    hours: optionalText(raw.hours, 200),
    acceptsAppointments: asBool(raw.accepts_appointments, false) ?? false,
  };
}

function parseList<T>(raw: unknown, parse: (item: unknown) => T | null, max: number): readonly T[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .slice(0, max)
    .map(parse)
    .filter((item): item is T => item !== null);
}

/** Returns null when the payload is not a usable hospital profile (receptionist features then stay off). */
export function parseHospital(raw: unknown): PublicHospital | null {
  if (!isRecord(raw)) return null;
  const id = asString(raw.id, 64);
  const name = asString(raw.name, 200);
  if (id === null || name === null) return null;
  return {
    id,
    name,
    isDemo: asBool(raw.is_demo, true) ?? true,
    address: optionalText(raw.address),
    mainPhone: parseContact(raw.main_phone),
    emergency: parseContact(raw.emergency),
    crisisLines: uniqueBy(parseList(raw.crisis_lines, parseContact, MAX_CRISIS_LINES), (c) => telHref(c.number)),
    handoff: parseContact(raw.handoff),
    visitingHours: optionalText(raw.visiting_hours),
    departments: uniqueBy(parseList(raw.departments, parseDepartment, MAX_DEPARTMENTS), (d) => d.id),
  };
}

/**
 * A dialable tel: URI from a validated display number (digits and a leading +). In international
 * format the national trunk prefix written "(0)" is not dialled: "+33 (0)4 72..." is tel:+33472...
 */
export function telHref(number: string): string {
  const trimmed = number.trim();
  const international = trimmed.startsWith("+");
  const dialled = international ? trimmed.replace(/\(\s*0\s*\)/g, "") : trimmed;
  return `tel:${international ? "+" : ""}${dialled.replace(/\D/g, "")}`;
}
