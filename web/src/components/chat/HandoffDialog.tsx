"use client";

import { XIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { forwardRef } from "react";
import type { PublicHospital } from "@/lib/api/client";
import { ContactLink } from "./ContactLink";

interface HandoffDialogProps {
  readonly hospital: PublicHospital | null;
  readonly onClose: () => void;
}

/** "Talk to a person": the hospital's human contact, always one tap away (from GET /api/v1/hospital). */
export const HandoffDialog = forwardRef<HTMLDialogElement, HandoffDialogProps>(function HandoffDialog({ hospital, onClose }, ref) {
  const t = useTranslations("Chat");
  // Keyed by role: the front desk and the switchboard may share a number (review T16).
  const contacts = [
    hospital?.handoff ? { role: "handoff", contact: hospital.handoff, tone: "brand" as const } : null,
    hospital?.mainPhone ? { role: "main", contact: { ...hospital.mainPhone, label: hospital.mainPhone.label || t("mainPhone") }, tone: "quiet" as const } : null,
    hospital?.emergency ? { role: "emergency", contact: { ...hospital.emergency, label: hospital.emergency.label || t("emergencyLabel") }, tone: "danger" as const } : null,
  ].filter((c) => c !== null);
  return (
    <dialog ref={ref} aria-labelledby="handoff-title" onClose={onClose} className="handoff-dialog" data-testid="handoff-dialog">
      <div className="grid gap-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 id="handoff-title" className="text-2xl font-bold">
            {t("handoffTitle")}
          </h2>
          <form method="dialog">
            <button type="submit" className="btn btn-ghost btn-icon -me-2 -mt-1" aria-label={t("drawer.close")}>
              <XIcon size={22} aria-hidden="true" />
            </button>
          </form>
        </div>
        <p className="text-ink-2">{t("handoffBody")}</p>
        {hospital ? (
          <p className="font-semibold" data-testid="hospital-name">
            {hospital.name}
          </p>
        ) : null}
        {contacts.length > 0 ? (
          <ul className="grid gap-2">
            {contacts.map(({ role, contact, tone }) => (
              <li key={role} className="grid">
                <ContactLink contact={contact} callLabel={t("call", { label: contact.label })} tone={tone} />
              </li>
            ))}
          </ul>
        ) : (
          <p>{t("seekCareUrgentNoNumber")}</p>
        )}
        {hospital?.address ? (
          <p className="text-sm text-ink-2">
            <span className="font-semibold">{t("address")}: </span>
            {hospital.address}
          </p>
        ) : null}
        {hospital?.visitingHours ? (
          <p className="text-sm text-ink-2">
            <span className="font-semibold">{t("visitingHours")}: </span>
            {hospital.visitingHours}
          </p>
        ) : null}
      </div>
    </dialog>
  );
});
