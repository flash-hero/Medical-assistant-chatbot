/**
 * Streamed answers arrive a sentence at a time. The UI reveals them at a steady pace instead, and
 * only ever cuts the text where the restricted Markdown is complete (no half "[1" or open "**").
 */

const MIN_STEP = 3;
const CATCH_UP = 0.08;

/** The smallest index >= `index` where `text.slice(0, i)` renders without partial markup. */
export function safeCut(text: string, index: number): number {
  let cut = Math.min(Math.max(0, index), text.length);
  const open = text.lastIndexOf("[", cut - 1);
  if (open !== -1 && text.lastIndexOf("]", cut - 1) < open) {
    const close = text.indexOf("]", open);
    if (close !== -1 && /^\[[\d,\s]*$/.test(text.slice(open, cut))) cut = close + 1;
  }
  const bolds = text.slice(0, cut).split("**").length - 1;
  if (bolds % 2 === 1) {
    const close = text.indexOf("**", cut);
    // An opening ** that never closes stays literal text, so cutting after it is safe.
    if (close !== -1) cut = close + 2;
  }
  return cut;
}

/** One animation frame's progress toward `target`: proportional catch-up, with a minimum pace. */
export function nextRevealLength(shown: number, target: number): number {
  const remaining = target - shown;
  if (remaining <= 2 * MIN_STEP) return target; // the last few characters snap in
  return Math.min(target, shown + Math.max(MIN_STEP, Math.ceil(remaining * CATCH_UP)));
}
