"use client";

import { HeadsetIcon, InfoIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import type { NoticeEvent } from "@/lib/chat/types";
import { useChatActions } from "./ChatContext";

/** Server notices (degraded mode, source language, handoff...). The demo notice is already a banner. */
export function NoticeList({ notices }: { readonly notices: readonly NoticeEvent[] }) {
  const t = useTranslations("Chat");
  const { demoBannerShown, openHandoff } = useChatActions();
  const visible = notices.filter((n) => !(n.code === "demo_mode" && demoBannerShown));
  if (visible.length === 0) return null;
  return (
    <ul className="grid gap-2" data-testid="notices">
      {visible.map((notice) => (
        <li
          key={notice.code}
          data-code={notice.code}
          className={`flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 text-sm ${
            notice.code === "degraded" ? "border border-warn-line bg-warn-soft text-warn-ink" : "bg-surface-2 text-ink-2"
          }`}
        >
          <InfoIcon size={18} aria-hidden="true" className="shrink-0" />
          <span className="flex-1">{notice.message}</span>
          {notice.code === "handoff_available" ? (
            <button type="button" className="btn btn-quiet min-h-11 bg-surface text-sm" onClick={(e) => openHandoff(e.currentTarget)}>
              <HeadsetIcon size={18} aria-hidden="true" />
              {t("handoff")}
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
