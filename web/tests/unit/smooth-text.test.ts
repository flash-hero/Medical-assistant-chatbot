import { describe, expect, it } from "vitest";
import { nextRevealLength, safeCut } from "@/lib/chat/smooth-text";

describe("safeCut", () => {
  it("never ends inside a citation marker", () => {
    const text = "Measured over three months [12]. More.";
    expect(safeCut(text, text.indexOf("[") + 2)).toBe(text.indexOf("]") + 1);
  });

  it("never leaves an unclosed bold span", () => {
    const text = "This is **very important** indeed.";
    expect(safeCut(text, text.indexOf("very") + 2)).toBe(text.indexOf("important") + "important**".length);
  });

  it("keeps a lone ** that is never closed as literal text", () => {
    expect(safeCut("Use ** carefully", 6)).toBe(6);
  });

  it("clamps to the text bounds", () => {
    expect(safeCut("abc", 10)).toBe(3);
    expect(safeCut("abc", -1)).toBe(0);
  });
});

describe("nextRevealLength", () => {
  it("advances at least a few characters and catches up proportionally", () => {
    expect(nextRevealLength(0, 10)).toBeGreaterThanOrEqual(3);
    expect(nextRevealLength(0, 1000)).toBeGreaterThan(50);
    expect(nextRevealLength(995, 1000)).toBe(1000);
  });
});
