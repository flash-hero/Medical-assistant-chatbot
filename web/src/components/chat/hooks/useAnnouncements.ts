"use client";

import { useEffect, useRef, useState } from "react";
import { createAnnouncer, type Announcer } from "@/lib/a11y/announcer";
import type { Turn } from "@/lib/chat/reducer";

export interface Announcement {
  readonly id: number;
  readonly text: string;
}

/**
 * Drives the polite live region from the latest turn: "answering" once, then whole sentences at most
 * every 2.5 s, then the rest of the confirmed answer. Never one update per token. A stopped turn
 * says so (review T8): its note appears where the Stop button was, which a screen reader may not visit.
 */
export function useAnnouncements(turn: Turn | undefined, answeringText: string, stoppedText: string): Announcement {
  const [announcement, setAnnouncement] = useState<Announcement>({ id: 0, text: "" });
  const announcerRef = useRef<Announcer | null>(null);
  const turnIdRef = useRef<string | null>(null);
  const answeredRef = useRef<string | null>(null);
  const stoppedRef = useRef<string | null>(null);

  useEffect(() => {
    const announcer = createAnnouncer((text) => setAnnouncement((a) => ({ id: a.id + 1, text })));
    announcerRef.current = announcer;
    return () => announcer.dispose();
  }, []);

  useEffect(() => {
    const announcer = announcerRef.current;
    if (!announcer || !turn) return;
    if (turnIdRef.current !== turn.id) {
      turnIdRef.current = turn.id;
      answeredRef.current = null;
      announcer.reset();
      setAnnouncement((a) => ({ id: a.id + 1, text: answeringText }));
    }
    if (turn.phase === "stopped") {
      if (stoppedRef.current === turn.id) return;
      stoppedRef.current = turn.id;
      announcer.reset();
      setAnnouncement((a) => ({ id: a.id + 1, text: stoppedText }));
      return;
    }
    if (turn.answer && answeredRef.current !== turn.id) {
      answeredRef.current = turn.id;
      if (turn.answer.replaces_stream || turn.streamed === "") announcer.replace(turn.answer.text);
      else announcer.finish(turn.answer.text);
    } else if (!turn.answer && turn.streamed !== "") {
      announcer.stream(turn.streamed);
    }
  }, [turn, answeringText, stoppedText]);

  return announcement;
}
