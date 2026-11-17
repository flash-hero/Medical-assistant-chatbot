/**
 * Safety events are kept per kind and shown highest priority first (review T2): a later, lower-priority
 * event (abuse disclosure) must never replace an emergency banner. Priority is the server's
 * SAFETY_ORDER (app/pipeline/engine.py): emergency, self-harm, harm to others, abuse disclosure.
 */

import type { PhoneContact, PublicHospital } from "@/lib/api/hospital";
import { telHref } from "@/lib/api/hospital";
import { SAFETY_KINDS, type Contact, type SafetyEvent, type SafetyKind } from "./types";

const PRIORITY: ReadonlyMap<SafetyKind, number> = new Map(SAFETY_KINDS.map((kind, i) => [kind, i]));

function rank(event: SafetyEvent): number {
  return PRIORITY.get(event.kind) ?? 0;
}

/** A new list with `event` in place of any event of the same kind, sorted by priority. */
export function mergeSafety(list: readonly SafetyEvent[], event: SafetyEvent): readonly SafetyEvent[] {
  return [...list.filter((e) => e.kind !== event.kind), event].sort((a, b) => rank(a) - rank(b));
}

/** Merge two lists; `newer` wins for a kind present in both. */
export function mergeSafetyLists(older: readonly SafetyEvent[], newer: readonly SafetyEvent[]): readonly SafetyEvent[] {
  return newer.reduce(mergeSafety, older);
}

function hospitalFallback(kind: SafetyKind, hospital: PublicHospital): readonly PhoneContact[] {
  const emergency = hospital.emergency ? [hospital.emergency] : [];
  return kind === "self_harm" ? [...hospital.crisisLines, ...emergency] : emergency;
}

/**
 * One contact list for the banner: the events' own contacts in priority order, each number once.
 * When no event carries a contact (drifted or fallback event), the hospital's verified numbers are used.
 */
export function safetyContacts(events: readonly SafetyEvent[], hospital: PublicHospital | null): readonly Contact[] {
  const own = events.flatMap((e) => e.contacts);
  const all = own.length > 0 || hospital === null ? own : events.flatMap((e) => hospitalFallback(e.kind, hospital));
  const seen = new Set<string>();
  return all.filter((contact) => {
    const key = telHref(contact.number);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
