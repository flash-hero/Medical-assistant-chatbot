"use client";

import { CheckCircleIcon, LockSimpleIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent } from "react";
import type { Turn } from "@/lib/chat/reducer";
import type { FormEvent as ChatFormEvent } from "@/lib/chat/types";
import { buildAppointmentBody, validateForm, type FormErrors } from "@/lib/forms/validate";
import { AppointmentField, errorText } from "./AppointmentFields";
import { useChatActions } from "./ChatContext";

function Success({ requestId, message }: { readonly requestId: string; readonly message: string }) {
  const t = useTranslations("Chat.form");
  return (
    <div role="status" className="grid gap-1 rounded-2xl bg-brand-soft p-4 text-brand-ink" data-testid="appointment-success">
      <p className="flex items-center gap-2 text-lg font-bold">
        <CheckCircleIcon size={24} weight="fill" aria-hidden="true" />
        {t("successTitle")}
      </p>
      {message ? <p>{message}</p> : null}
      <p className="font-semibold" dir="auto">
        {t("reference", { id: requestId })}
      </p>
    </div>
  );
}

const CONSENT_NAME = "consent";

/**
 * Move focus to the first invalid control, in visual order. Called right after validation, before
 * React re-renders, so it looks controls up by name rather than by the not-yet-set aria-invalid.
 */
function focusFirstInvalid(form: HTMLFormElement | null, order: readonly string[], errors: FormErrors): void {
  const name = order.find((candidate) => errors[candidate] !== undefined);
  const control = name === undefined ? null : form?.elements.namedItem(name);
  if (control instanceof HTMLElement) control.focus();
}

/** Appointment request form rendered from the `form` event. Its contents go to staff, never to the model. */
export function AppointmentForm({ turn, form }: { readonly turn: Turn; readonly form: ChatFormEvent }) {
  const t = useTranslations("Chat");
  const { submitForm } = useChatActions();
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const [values, setValues] = useState<Readonly<Record<string, string>>>({});
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [status, setStatus] = useState<"idle" | "sending" | "error">("idle");

  if (turn.formResult) return <Success requestId={turn.formResult.requestId} message={turn.formResult.message} />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const found = validateForm(form.fields, values, consent);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      focusFirstInvalid(formRef.current, [...form.fields.map((f) => f.name), CONSENT_NAME], found);
      return;
    }
    setStatus("sending");
    submitForm(turn, buildAppointmentBody(form.fields, values, consent)).catch(() => setStatus("error"));
  };

  const errorCount = Object.keys(errors).length;
  return (
    <form ref={formRef} noValidate onSubmit={onSubmit} aria-labelledby={`${id}-title`} className="grid gap-4 rounded-2xl border border-line bg-surface p-4 sm:p-5" data-testid="appointment-form">
      <div className="grid gap-1">
        <h3 id={`${id}-title`} className="text-lg font-bold">
          {form.title}
        </h3>
        <p className="text-ink-2">{form.description}</p>
      </div>
      {errorCount > 0 ? (
        <p role="alert" className="font-semibold text-danger-ink">
          {t("form.fixErrors", { count: errorCount })}
        </p>
      ) : null}
      {form.fields.map((field) => (
        <AppointmentField
          key={field.name}
          field={field}
          id={`${id}-${field.name}`}
          value={values[field.name] ?? ""}
          error={errors[field.name]}
          onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
        />
      ))}
      <div className="grid gap-1.5">
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            name={CONSENT_NAME}
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            aria-invalid={errors.consent ? true : undefined}
            aria-describedby={errors.consent ? `${id}-consent-error` : undefined}
            className="mt-1 size-5 shrink-0 accent-brand"
          />
          <span>{t("form.consent")}</span>
        </label>
        {errors.consent ? (
          <p id={`${id}-consent-error`} className="text-sm font-semibold text-danger-ink">
            {errorText(t, errors.consent)}
          </p>
        ) : null}
      </div>
      <p className="flex items-center gap-2 text-sm text-ink-2">
        <LockSimpleIcon size={18} aria-hidden="true" className="shrink-0" />
        {t("form.privacyNote")}
      </p>
      {status === "error" ? (
        <p role="alert" className="font-semibold text-danger-ink">
          {t("form.error")}
        </p>
      ) : null}
      <button type="submit" className="btn btn-primary w-fit" disabled={status === "sending"}>
        {status === "sending" ? t("form.sending") : t("form.submit")}
      </button>
    </form>
  );
}
