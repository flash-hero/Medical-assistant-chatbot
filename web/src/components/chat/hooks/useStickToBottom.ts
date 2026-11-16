"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * Keeps the newest content in view while the reader is at the bottom of the conversation; a reader who
 * scrolled up to re-read is left alone. Watches a sentinel element with IntersectionObserver.
 */
export function useStickToBottom(sentinel: RefObject<HTMLElement | null>, contentKey: unknown): void {
  const atBottom = useRef(true);

  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        atBottom.current = entry?.isIntersecting ?? true;
      },
      { rootMargin: "0px 0px 160px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [sentinel]);

  useEffect(() => {
    if (!atBottom.current) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    sentinel.current?.scrollIntoView({ block: "end", behavior: reduced ? "auto" : "smooth" });
  }, [sentinel, contentKey]);
}
