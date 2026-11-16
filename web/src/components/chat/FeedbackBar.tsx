"use client";

import { ThumbsDownIcon, ThumbsUpIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";
import type { FeedbackReason } from "@/lib/api/client";
import type { Turn } from "@/lib/chat/reducer";
import { useChatActions } from "./ChatContext";

const REASONS: readonly FeedbackReason[] = ["incorrect", "unsafe", "unhelpful", "other"];
const MAX_COMMENT = 500;
type Status = "idle" | "asking" | "sending" | "sent" | "error";

function ReasonForm({ onSubmit, sending }: { readonly onSubmit: (reason: FeedbackReason, comment: string) => void; readonly sending: boolean }) {
  const t = useTranslations("Chat.feedback");
  const id = useId();
  const [reason, setReason] = useState<FeedbackReason>("incorrect");
  const [comment, setComment] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(reason, comment.trim());
  };
  return (
    <form onSubmit={submit} className="grid gap-3 rounded-2xl border border-line bg-surface p-4" data-testid="feedback-form">
      <fieldset className="grid gap-1">
        <legend className="mb-1 font-semibold">{t("reasonLabel")}</legend>
        {REASONS.map((r) => (
          <label key={r} className="flex min-h-11 cursor-pointer items-center gap-3">
            <input type="radio" name={`${id}-reason`} value={r} checked={reason === r} onChange={() => setReason(r)} className="size-5 accent-brand" />
            {t(`reasons.${r}`)}
          </label>
        ))}
      </fieldset>
      <label className="grid gap-1.5" htmlFor={`${id}-comment`}>
        <span className="text-sm font-semibold">{t("commentLabel")}</span>
        <textarea id={`${id}-comment`} className="field-input min-h-20" maxLength={MAX_COMMENT} value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>
      <button type="submit" className="btn btn-primary w-fit" disabled={sending}>
        {t("submit")}
      </button>
    </form>
  );
}

/** Thumbs up sends at once; thumbs down asks why (optional comment, no personal details). */
export function FeedbackBar({ turn }: { readonly turn: Turn }) {
  const t = useTranslations("Chat.feedback");
  const { sendFeedback } = useChatActions();
  const [status, setStatus] = useState<Status>(turn.feedback ? "sent" : "idle");
  const send = (rating: "up" | "down", reason?: FeedbackReason, comment?: string) => {
    setStatus("sending");
    sendFeedback(turn, { rating, ...(reason ? { reason } : {}), ...(comment ? { comment } : {}) })
      .then(() => setStatus("sent"))
      .catch(() => setStatus("error"));
  };
  if (status === "sent") return <p className="text-sm text-ink-2" role="status">{t("thanks")}</p>;
  return (
    <div className="grid gap-2" data-testid="feedback">
      <div className="flex items-center gap-1">
        <span className="me-2 text-sm text-ink-2">{t("question")}</span>
        <button type="button" className="btn btn-ghost btn-icon" aria-label={t("up")} aria-pressed={false} onClick={() => send("up")} disabled={status === "sending"}>
          <ThumbsUpIcon size={22} aria-hidden="true" />
        </button>
        <button type="button" className="btn btn-ghost btn-icon" aria-label={t("down")} aria-pressed={status === "asking"} aria-expanded={status === "asking"} onClick={() => setStatus("asking")} disabled={status === "sending"}>
          <ThumbsDownIcon size={22} aria-hidden="true" />
        </button>
      </div>
      {status === "asking" ? <ReasonForm sending={false} onSubmit={(reason, comment) => send("down", reason, comment)} /> : null}
      {status === "error" ? (
        <p className="text-sm text-danger-ink" role="alert">
          {t("error")}
        </p>
      ) : null}
    </div>
  );
}
