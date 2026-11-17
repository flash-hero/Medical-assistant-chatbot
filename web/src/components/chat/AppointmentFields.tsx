"use client";

import { useTranslations } from "next-intl";
import type { FormField } from "@/lib/chat/types";
import type { FieldError } from "@/lib/forms/validate";

const AUTOCOMPLETE: Readonly<Record<string, string>> = {
  full_name: "name",
  name: "name",
  phone: "tel",
  email: "email",
};

const INPUT_TYPES = { text: "text", tel: "tel", email: "email", date: "date" } as const;

export function errorText(t: ReturnType<typeof useTranslations<"Chat">>, error: FieldError): string {
  switch (error.code) {
    case "required":
    case "option":
      return t("form.requiredError");
    case "tooLong":
      return t("form.tooLong", { max: error.max });
    case "email":
      return t("form.emailError");
    case "phone":
      return t("form.phoneError");
    case "date":
      return t("form.requiredError");
    case "consent":
      return t("form.consentError");
  }
}

interface FieldProps {
  readonly field: FormField;
  readonly id: string;
  readonly value: string;
  readonly error: FieldError | undefined;
  readonly onChange: (value: string) => void;
}

/** One server-described field: label above, error below, described-by wiring for screen readers. */
export function AppointmentField({ field, id, value, error, onChange }: FieldProps) {
  const t = useTranslations("Chat");
  const errorId = `${id}-error`;
  const common = {
    id,
    name: field.name,
    value,
    required: field.required,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
    className: "field-input",
  } as const;
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="font-semibold">
        {field.label}
        {field.required ? <span className="ms-1 text-sm font-normal text-ink-2">({t("form.required")})</span> : null}
      </label>
      {field.kind === "select" ? (
        <select {...common} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t("form.chooseOption")}</option>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : field.kind === "textarea" ? (
        <textarea {...common} maxLength={field.max_length} rows={3} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input
          {...common}
          type={INPUT_TYPES[field.kind]}
          maxLength={field.kind === "date" ? undefined : field.max_length}
          autoComplete={AUTOCOMPLETE[field.name] ?? "off"}
          dir={field.kind === "tel" || field.kind === "email" ? "ltr" : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {error ? (
        <p id={errorId} className="text-sm font-semibold text-danger-ink">
          {errorText(t, error)}
        </p>
      ) : null}
    </div>
  );
}
