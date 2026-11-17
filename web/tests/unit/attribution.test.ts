import { describe, expect, it } from "vitest";
import seed from "@/content/attribution.json";
import { featuredSources, parseAttribution } from "@/lib/attribution";

const MEDLINEPLUS = "medlineplus_topics";

describe("parseAttribution", () => {
  it("accepts every source of the synced file, MedlinePlus included", () => {
    const result = parseAttribution(seed);
    expect(result.generatedOn).toBe(seed.generated_on);
    expect(result.sources).toHaveLength(seed.sources.length);
    expect(result.sources.length).toBeGreaterThan(1);
    expect(result.sources.find((s) => s.id === MEDLINEPLUS)).toMatchObject({
      publisher: "U.S. National Library of Medicine",
      homepage: "https://medlineplus.gov/",
      license: { attribution: "Source: MedlinePlus, National Library of Medicine", verifiedOn: "2026-11-15" },
    });
  });

  it("gives every shown source a licence with evidence and a credit line", () => {
    for (const source of parseAttribution(seed).sources) {
      expect(source.license.evidenceUrl, source.id).toMatch(/^https:\/\//);
      expect(source.license.attribution, source.id).not.toBe("");
    }
  });

  it("drops entries with unsafe URLs or missing licence evidence", () => {
    const base = seed.sources.find((s) => s.id === MEDLINEPLUS)!;
    const result = parseAttribution({
      ...seed,
      sources: [
        { ...base, id: "js", homepage: "javascript:alert(1)" },
        { ...base, id: "noevidence", license: { ...base.license, evidence_url: "" } },
        { ...base, id: "ok_one" },
        "not an object",
      ],
    });
    expect(result.sources.map((s) => s.id)).toEqual(["ok_one"]);
  });

  it("returns an empty list for a malformed file", () => {
    expect(parseAttribution(null)).toEqual({ generatedOn: null, sources: [] });
    expect(parseAttribution({ sources: "nope" })).toEqual({ generatedOn: null, sources: [] });
  });
});

describe("featuredSources", () => {
  const { sources } = parseAttribution(seed);

  it("keeps the first source of each publisher, in file order, up to the cap", () => {
    const featured = featuredSources(sources, 6);
    expect(featured.length).toBeLessThanOrEqual(6);
    expect(new Set(featured.map((s) => s.publisher)).size).toBe(featured.length);
    const firstOfEach = sources.filter((s, i) => sources.findIndex((o) => o.publisher === s.publisher) === i);
    expect(featured).toEqual(firstOfEach.slice(0, 6));
  });

  it("returns nothing for an empty list or a zero cap", () => {
    expect(featuredSources([], 6)).toEqual([]);
    expect(featuredSources(sources, 0)).toEqual([]);
  });
});
