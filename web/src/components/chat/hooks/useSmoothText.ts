"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { nextRevealLength, safeCut } from "@/lib/chat/smooth-text";

const FRAME_MS = 33; // ~30 updates per second is smooth for text and cheap for React

/**
 * Reveals streamed text at a steady pace. Text that is not a continuation of what is shown (a
 * replaced or verified answer) appears at once, as it does under reduced motion.
 */
export function useSmoothText(text: string, enabled: boolean): string {
  const reduced = useReducedMotion();
  const smooth = enabled && !reduced;
  const initial = smooth ? 0 : text.length;
  const shownRef = useRef(initial);
  const previous = useRef(text);
  const [shown, setShown] = useState(initial);

  useEffect(() => {
    const continues = text.startsWith(previous.current);
    previous.current = text;
    if (!smooth || !continues || shownRef.current >= text.length) {
      shownRef.current = text.length;
      setShown(text.length);
      return;
    }
    let last = 0;
    let frame = 0;
    const step = (now: number) => {
      if (now - last >= FRAME_MS) {
        last = now;
        shownRef.current = safeCut(text, nextRevealLength(shownRef.current, text.length));
        setShown(shownRef.current);
        if (shownRef.current >= text.length) return;
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [text, smooth]);

  return smooth ? text.slice(0, Math.min(shown, text.length)) : text;
}
