"use client";

import { useEffect } from "react";

/**
 * Starts the landing choreography after hydration. Under prefers-reduced-motion nothing loads:
 * the page is already complete and static without it.
 */
export function LandingMotion() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let disposed = false;
    let dispose: (() => void) | null = null;
    import("./landing-motion")
      .then(({ startLandingMotion }) => startLandingMotion())
      .then((stop) => {
        if (disposed) stop();
        else dispose = stop;
      })
      .catch((error: unknown) => {
        // Motion is an enhancement: the static page stays fully usable.
        console.warn("Landing motion unavailable", error);
      });
    return () => {
      disposed = true;
      dispose?.();
    };
  }, []);
  return null;
}
