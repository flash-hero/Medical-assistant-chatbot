"use client";

import { CheckCircleIcon, LockSimpleIcon } from "@/components/ui/icons";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api/errors";
import type { PublicHospital } from "@/lib/api/hospital";
import type { Turn } from "@/lib/chat/reducer";
import type { FormEvent as ChatFormEvent } from "@/lib/chat/types";
import { buildAppointmentBody, validateForm, type FormErrors } from "@/lib/forms/validate";
import { dirOf } from "@/lib/i18n/text-language";
import { AppointmentField, errorText } from "./AppointmentFields";
import { useChatActions } from "./ChatContext";

interface SuccessProps {
  readonly requestId: string;
  readonly message: string;
  /** The form this replaces had focus inside it: take the focus (review T8). */
  readonly takeFocus: boolean;
}

function Success({ requestId, message, takeFocus }: SuccessProps) {
  const t = useTranslations("Chat.form");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (takeFocus) ref.current?.focus();
  }, [takeFocus]);
  return (
    <div ref={ref} tabIndex={-1} role="status" className="grid gap-1 rounded-2xl bg-brand-soft p-4 text-brand-ink" data-testid="appointment-success">
      <p className="flex items-center gap-2 text-lg font-bold">
        <CheckCircleIcon size={24} weight="fill" aria-hidden="true" />
        {t("successTitle")}
      </p>
      {message ? <p dir={dirOf(message)}>{message}</p> : null}
      <p className="font-semibold" dir="auto">
        {t("reference", { id: requestId })}
      </p>
    </div>
  );
}

const CONSENT_NAME = "consent";
const DEPARTMENT_FIELD = "department_id";
/** Submission failures with their own explanation; anything else gets the generic text. */
const SUBMIT_ERRORS = new Set(["invalid_input", "rate_limited", "not_found", "unauthorized", "network"]);

function submitErrorCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const code = error.code === "timeout" ? "network" : error.code;
  return SUBMIT_ERRORS.has(code) ? code : null;
}

/** "internal_medicine" -> "Internal medicine": only when the hospital profile has no name for an id. */
function humanizeId(id: string): string {
  const words = id.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The form's department options are ids (contract); patients see the profile's localised names (T3). */
function departmentLabel(hospital: PublicHospital | null): (id: string) => string {
  return (id) => hospital?.departments.find((d) => d.id === id)?.name ?? humanizeId(id);
}

function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Move focus to the first invalid control, in visual order. Called right after validation, before
 * React re-renders, so it looks controls up by name rather than by the not-yet-set aria-invalid.
 */
function focusFirstInvalid(form: HTMLFormElement | null, order: readonly string[], errors: FormErrors): void {
  const name = order.find((candidate) => errors[candidate] !== undefined);
  const control = name === undefined ? null : form?.elements.namedItem(name);
  if (control instanceof HTMLElement) control.focus();
}

/**
 * Appointment request form rendered from the `form` event. Its contents go to staff, never to the model.
 * A retry of the same request reuses its idempotency key; a changed request gets a new one (T14).
 */
export function AppointmentForm({ turn, form }: { readonly turn: Turn; readonly form: ChatFormEvent }) {
  const t = useTranslations("Chat");
  const { submitForm, hospital } = useChatActions();
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const lastAttempt = useRef<{ readonly key: string; readonly body: string } | null>(null);
  const [values, setValues] = useState<Readonly<Record<string, string>>>({});
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [status, setStatus] = useState<"idle" | "sending" | "error">("idle");
  const [failure, setFailure] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  if (turn.formResult) return <Success requestId={turn.formResult.requestId} message={turn.formResult.message} takeFocus={submitted} />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const found = validateForm(form.fields, values, consent);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      focusFirstInvalid(formRef.current, [...form.fields.map((f) => f.name), CONSENT_NAME], found);
      return;
    }
    const body = buildAppointmentBody(form.fields, values, consent);
    const serialized = JSON.stringify(body);
    const key = lastAttempt.current?.body === serialized ? lastAttempt.current.key : newIdempotencyKey();
    lastAttempt.current = { key, body: serialized };
    setStatus("sending");
    setSubmitted(true);
    submitForm(turn, body, key).catch((error: unknown) => {
      setFailure(submitErrorCode(error));
      setStatus("error");
    });
  };
  const optionLabel = departmentLabel(hospital);

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
          optionLabel={field.name === DEPARTMENT_FIELD ? optionLabel : undefined}
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
        <p role="alert" className="font-semibold text-danger-ink" data-testid="appointment-error">
          {failure ? t(`form.errors.${failure}`) : t("form.error")}
        </p>
      ) : null}
      <button type="submit" className="btn btn-primary w-fit" disabled={status === "sending"}>
        {status === "sending" ? t("form.sending") : t("form.submit")}
      </button>
    </form>
  );
}
