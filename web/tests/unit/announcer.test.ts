import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { completedSentences, createAnnouncer, toPlainText } from "@/lib/a11y/announcer";

describe("toPlainText", () => {
  it("drops markdown markers and citation numbers", () => {
    expect(toPlainText("**Bold** text [1] and [2, 3].\n- item")).toBe("Bold text and. item");
  });
});

describe("completedSentences", () => {
  it("returns only whole sentences after the cursor", () => {
    expect(completedSentences("One. Two", 0)).toEqual({ text: "One.", end: 4 });
    expect(completedSentences("One. Two. Thr", 4)).toEqual({ text: "Two.", end: 9 });
    expect(completedSentences("No end yet", 0)).toEqual({ text: "", end: 0 });
    expect(completedSentences("واحد. اثنان؟ ثلاثة", 0)).toEqual({ text: "واحد. اثنان؟", end: 12 });
  });
});

describe("createAnnouncer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("throttles streamed text to whole sentences at most once per interval", () => {
    const emitted: string[] = [];
    const announcer = createAnnouncer((text) => emitted.push(text), 2000);
    announcer.stream("First sentence. Sec");
    expect(emitted).toEqual(["First sentence."]);
    announcer.stream("First sentence. Second one. Third");
    announcer.stream("First sentence. Second one. Third one. Fou");
    expect(emitted).toHaveLength(1);
    vi.advanceTimersByTime(2000);
    expect(emitted).toEqual(["First sentence.", "Second one. Third one."]);
  });

  it("flushes the rest on finish and resets", () => {
    const emitted: string[] = [];
    const announcer = createAnnouncer((text) => emitted.push(text), 2000);
    announcer.stream("Alpha. Beta");
    announcer.finish("Alpha. Beta gamma.");
    expect(emitted).toEqual(["Alpha.", "Beta gamma."]);
    announcer.finish("Alpha. Beta gamma.");
    expect(emitted).toHaveLength(2);
    announcer.reset();
    announcer.finish("New answer.");
    expect(emitted.at(-1)).toBe("New answer.");
  });

  it("announces a replaced answer in full", () => {
    const emitted: string[] = [];
    const announcer = createAnnouncer((text) => emitted.push(text), 2000);
    announcer.stream("Draft one. Draft");
    announcer.replace("Corrected answer.");
    expect(emitted).toEqual(["Draft one.", "Corrected answer."]);
  });

  it("cancels pending timers on dispose", () => {
    const emitted: string[] = [];
    const announcer = createAnnouncer((text) => emitted.push(text), 2000);
    announcer.stream("A. ");
    announcer.stream("A. B. ");
    announcer.dispose();
    vi.advanceTimersByTime(5000);
    expect(emitted).toEqual(["A."]);
  });
});
