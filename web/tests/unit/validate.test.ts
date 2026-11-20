import { describe, expect, it } from "vitest";
import { asHttpUrl, isIsoDate, truncate } from "@/lib/validate";

describe("T17 asHttpUrl", () => {
  it("accepts plain http(s) URLs", () => {
    expect(asHttpUrl("https://medlineplus.gov/diabetes.html")).toBe("https://medlineplus.gov/diabetes.html");
    expect(asHttpUrl("http://example.org")).toBe("http://example.org/");
  });

  it("rejects URLs with user info, which can disguise the real host", () => {
    expect(asHttpUrl("https://medlineplus.gov@evil.example/")).toBeNull();
    expect(asHttpUrl("https://user:pass@example.org/")).toBeNull();
    expect(asHttpUrl("https://:secret@example.org/")).toBeNull();
  });

  it("rejects other schemes and junk", () => {
    for (const value of ["javascript:alert(1)", "data:text/html,x", "/relative", "", 42, null]) expect(asHttpUrl(value)).toBeNull();
  });
});

describe("T11 isIsoDate", () => {
  it("accepts real calendar dates only", () => {
    expect(isIsoDate("2025-09-12")).toBe(true);
    expect(isIsoDate("2024-02-29")).toBe(true);
    for (const value of ["2025-13-45", "2025-02-29", "2025-9-12", "2025-09-12T00:00:00Z", "", 20250912]) expect(isIsoDate(value)).toBe(false);
  });
});

describe("T4 truncate", () => {
  it("cuts at a code point boundary", () => {
    expect(truncate("abcdef", 3)).toBe("abc");
    expect(truncate("ab", 3)).toBe("ab");
    expect(truncate("a😀b", 2)).toBe("a");
  });
});
