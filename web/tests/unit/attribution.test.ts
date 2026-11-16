import { describe, expect, it } from "vitest";
import seed from "@/content/attribution.json";
import { parseAttribution } from "@/lib/attribution";

describe("parseAttribution", () => {
  it("accepts the seed file with the MedlinePlus entry", () => {
    const result = parseAttribution(seed);
    expect(result.generatedOn).toBe("2026-11-16");
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0]).toMatchObject({
      id: "medlineplus_topics",
      publisher: "U.S. National Library of Medicine",
      homepage: "https://medlineplus.gov/",
      license: { attribution: "Source: MedlinePlus, National Library of Medicine", verifiedOn: "2026-11-15" },
    });
  });

  it("drops entries with unsafe URLs or missing licence evidence", () => {
    const base = seed.sources[0]!;
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
