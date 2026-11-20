import { describe, expect, it } from "vitest";
import type { PublicHospital } from "@/lib/api/hospital";
import { mergeSafety, mergeSafetyLists, safetyContacts } from "@/lib/chat/safety";
import type { SafetyEvent } from "@/lib/chat/types";

const event = (kind: SafetyEvent["kind"], contacts: SafetyEvent["contacts"] = [], over: Partial<SafetyEvent> = {}): SafetyEvent => ({
  type: "safety",
  kind,
  template_id: `${kind}.v1`,
  title: kind,
  message: `${kind} message`,
  contacts,
  sticky: true,
  language: null,
  ...over,
});

const c = (label: string, number: string) => ({ label, number, hours: "" });

const hospital: PublicHospital = {
  id: "demo",
  name: "Demo",
  isDemo: true,
  address: "",
  mainPhone: c("Switchboard", "+33 4 00 00 00 00"),
  emergency: c("Emergency", "112"),
  crisisLines: [c("Crisis line", "3114")],
  handoff: c("Front desk", "+33 4 00 00 00 01"),
  visitingHours: "",
  departments: [],
};

describe("T2 mergeSafety", () => {
  it("orders kinds by priority: emergency, self-harm, harm to others, abuse disclosure", () => {
    let list: readonly SafetyEvent[] = [];
    for (const kind of ["abuse_disclosure", "harm_to_others", "emergency", "self_harm"] as const) list = mergeSafety(list, event(kind));
    expect(list.map((e) => e.kind)).toEqual(["emergency", "self_harm", "harm_to_others", "abuse_disclosure"]);
  });

  it("replaces the event of the same kind and never mutates the input", () => {
    const first = [event("emergency")];
    const merged = mergeSafety(first, event("emergency", [], { title: "newer" }));
    expect(merged.map((e) => e.title)).toEqual(["newer"]);
    expect(first[0]?.title).toBe("emergency");
  });

  it("merges two lists, the second winning per kind", () => {
    const kept = [event("self_harm", [], { title: "old" }), event("abuse_disclosure")];
    const merged = mergeSafetyLists(kept, [event("self_harm", [], { title: "new" }), event("emergency")]);
    expect(merged.map((e) => `${e.kind}:${e.title}`)).toEqual(["emergency:emergency", "self_harm:new", "abuse_disclosure:abuse_disclosure"]);
  });
});

describe("T2 safetyContacts", () => {
  it("merges contacts in priority order without repeating a number", () => {
    const contacts = safetyContacts(
      [event("emergency", [c("Emergency", "112"), c("Switchboard", "+33 4 00 00 00 00")]), event("self_harm", [c("Crisis line", "3114"), c("Emergency", "1 12")])],
      null,
    );
    expect(contacts.map((x) => x.number)).toEqual(["112", "+33 4 00 00 00 00", "3114"]);
  });

  it("T4: falls back to the hospital's verified contacts when the events carry none", () => {
    expect(safetyContacts([event("emergency")], hospital).map((x) => x.number)).toEqual(["112"]);
    expect(safetyContacts([event("self_harm")], hospital).map((x) => x.number)).toEqual(["3114", "112"]);
    expect(safetyContacts([event("emergency")], null)).toEqual([]);
  });
});
