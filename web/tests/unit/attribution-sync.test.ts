import { describe, expect, it } from "vitest";
import { buildAttribution, GENERATED_FROM, isoDate, mergeSource } from "../../scripts/content/attribution-lib.mjs";

const LISTED = {
  id: "cdc",
  name: "CDC web content",
  publisher: "Centers for Disease Control and Prevention",
  homepage: "https://www.cdc.gov/",
  languages: ["en"],
  license_name: "Public domain (U.S. Government work) with CDC use conditions",
  attribution: "Source: CDC",
};

const RECORD = {
  id: "cdc",
  status: "active",
  trust_tier: 1,
  reuse_mode: "paraphrase_ok",
  license: {
    id: "public-domain-us-gov",
    name: "Public domain",
    evidence_url: "https://www.cdc.gov/other/agencymaterials.html",
    attribution: "Registry credit",
    conditions: ["Do not imply endorsement"],
    verified_on: new Date("2026-11-14T00:00:00Z"),
  },
};

describe("isoDate", () => {
  it("keeps YYYY-MM-DD from strings and YAML dates, rejects anything else", () => {
    expect(isoDate("2026-11-15")).toBe("2026-11-15");
    expect(isoDate(new Date("2026-11-15T00:00:00Z"))).toBe("2026-11-15");
    expect(isoDate("15/11/2026")).toBeNull();
    expect(isoDate(undefined)).toBeNull();
  });
});

describe("mergeSource", () => {
  it("takes names and credit lines from the listed file and licence facts from the registry", () => {
    expect(mergeSource(LISTED, RECORD)).toEqual({
      id: "cdc",
      name: "CDC web content",
      publisher: "Centers for Disease Control and Prevention",
      homepage: "https://www.cdc.gov/",
      languages: ["en"],
      trust_tier: 1,
      reuse_mode: "paraphrase_ok",
      license: {
        id: "public-domain-us-gov",
        name: "Public domain (U.S. Government work) with CDC use conditions",
        evidence_url: "https://www.cdc.gov/other/agencymaterials.html",
        attribution: "Source: CDC",
        conditions: ["Do not imply endorsement"],
        verified_on: "2026-11-14",
      },
    });
  });

  it("falls back to the registry when the listed file omits a credit line or licence name", () => {
    const bare = { id: LISTED.id, name: LISTED.name, publisher: LISTED.publisher, homepage: LISTED.homepage };
    const merged = mergeSource(bare, { ...RECORD, languages: ["en", "es"] });
    expect(merged?.license.name).toBe("Public domain");
    expect(merged?.license.attribution).toBe("Registry credit");
    expect(merged?.languages).toEqual(["en", "es"]);
  });

  it("refuses sources that are missing, inactive or without licence evidence", () => {
    expect(mergeSource(LISTED, undefined)).toBeNull();
    expect(mergeSource(LISTED, { ...RECORD, status: "candidate" })).toBeNull();
    expect(mergeSource(LISTED, { ...RECORD, license: { ...RECORD.license, evidence_url: "" } })).toBeNull();
  });
});

describe("buildAttribution", () => {
  it("keeps listed order, reports dropped ids and dates the file by the latest verification", () => {
    const listed = [LISTED, { ...LISTED, id: "orphan" }, { ...LISTED, id: "nih" }];
    const registry = { sources: [RECORD, { ...RECORD, id: "nih", license: { ...RECORD.license, verified_on: "2026-11-15" } }] };
    const { attribution, dropped } = buildAttribution(listed, registry);
    expect(attribution.sources.map((s) => s.id)).toEqual(["cdc", "nih"]);
    expect(dropped).toEqual(["orphan"]);
    expect(attribution.generated_on).toBe("2026-11-15");
    expect(attribution.generated_from).toBe(GENERATED_FROM);
    expect(attribution.version).toBe(1);
  });

  it("rejects a listed file that is not an array", () => {
    expect(() => buildAttribution({ sources: [] }, { sources: [] })).toThrow(TypeError);
  });

  it("produces an empty, undated file when nothing qualifies", () => {
    const { attribution, dropped } = buildAttribution([LISTED], null);
    expect(attribution.sources).toEqual([]);
    expect(attribution.generated_on).toBeNull();
    expect(dropped).toEqual(["cdc"]);
  });
});
