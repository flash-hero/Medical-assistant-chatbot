import { describe, expect, it } from "vitest";
import { isDemoMode } from "@/lib/chat/demo-mode";

describe("isDemoMode", () => {
  it("assumes demo while the session is unknown, so the banner is in the first render", () => {
    expect(isDemoMode(null, null)).toBe(true);
  });

  it("follows the session once it answers", () => {
    expect(isDemoMode(true, null)).toBe(true);
    expect(isDemoMode(false, null)).toBe(false);
  });

  it("lets a turn's meta event switch demo on, never off", () => {
    expect(isDemoMode(false, true)).toBe(true);
    expect(isDemoMode(true, false)).toBe(true);
    expect(isDemoMode(false, false)).toBe(false);
  });
});
