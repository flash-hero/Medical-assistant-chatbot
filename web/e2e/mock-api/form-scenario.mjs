/**
 * Appointment form event and server-side validation of its submission (mock of POST /appointments).
 * Mirrors the real server: app/pipeline/forms.py (fields, department ids as options, `consent` as a
 * one-option select) and app/api/schemas.py `AppointmentBody` (lengths, phone and e-mail rules).
 */
import { HOSPITAL } from "./fixtures.mjs";
import { TEXT } from "./texts.mjs";

const pick = (value, locale) => (value && typeof value === "object" && "en" in value ? value[locale] || value.en : value);

function bookable() {
  return HOSPITAL.departments.filter((d) => d.accepts_appointments);
}

/** Department options are ids: the UI must show the names from GET /api/v1/hospital (review T3). */
export function appointmentFormEvent(locale) {
  const label = (name) => pick(TEXT.form.labels[name], locale);
  return {
    form_id: "appointment_request",
    title: pick(TEXT.form.title, locale),
    description: pick(TEXT.form.description, locale),
    submit_url: "/api/v1/appointments",
    fields: [
      { name: "full_name", label: label("full_name"), kind: "text", required: true, options: [], max_length: 120 },
      { name: "phone", label: label("phone"), kind: "tel", required: true, options: [], max_length: 32 },
      { name: "email", label: label("email"), kind: "email", required: false, options: [], max_length: 254 },
      { name: "department_id", label: label("department_id"), kind: "select", required: true, options: bookable().map((d) => d.id), max_length: 200 },
      { name: "preferred_dates", label: label("preferred_dates"), kind: "textarea", required: true, options: [], max_length: 300 },
      { name: "reason", label: label("reason"), kind: "textarea", required: false, options: [], max_length: 500 },
      { name: "consent", label: label("consent"), kind: "select", required: true, options: ["yes"], max_length: 200 },
    ],
  };
}

const PHONE = /^\+?[0-9][0-9 ()\-.]{5,24}$/;
const EMAIL = /^[^@\s<>"'`]{1,64}@[^@\s<>"'`]{1,189}\.[^@\s<>"'`]{2,}$/;

/** Returns a list of invalid field names (empty when the body is acceptable). */
export function validateAppointment(body) {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return ["body"];
  const text = (v, max) => typeof v === "string" && v.trim() !== "" && v.length <= max;
  const invalid = [];
  if (!text(body.full_name, 120)) invalid.push("full_name");
  if (!text(body.phone, 32) || !PHONE.test(body.phone.trim())) invalid.push("phone");
  if (body.email !== undefined && !(typeof body.email === "string" && body.email.length <= 254 && EMAIL.test(body.email))) invalid.push("email");
  if (typeof body.department_id !== "string" || !bookable().some((d) => d.id === body.department_id)) invalid.push("department_id");
  if (!text(body.preferred_dates, 300)) invalid.push("preferred_dates");
  if (body.reason !== undefined && !(typeof body.reason === "string" && body.reason.length <= 500)) invalid.push("reason");
  if (body.consent !== true) invalid.push("consent");
  return invalid;
}

export function appointmentConfirmation(locale) {
  return pick(TEXT.form.confirmation, locale);
}
