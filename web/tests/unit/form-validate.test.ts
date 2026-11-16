import { describe, expect, it } from "vitest";
import type { FormField } from "@/lib/chat/types";
import { buildAppointmentBody, validateField, validateForm } from "@/lib/forms/validate";

const field = (over: Partial<FormField>): FormField => ({
  name: "full_name",
  label: "Name",
  kind: "text",
  required: false,
  options: [],
  max_length: 20,
  ...over,
});

describe("validateField", () => {
  it("checks required, length, email, phone, date and options", () => {
    expect(validateField(field({ required: true }), "  ")).toEqual({ code: "required" });
    expect(validateField(field({}), "")).toBeNull();
    expect(validateField(field({ max_length: 3 }), "abcd")).toEqual({ code: "tooLong", max: 3 });
    expect(validateField(field({ kind: "email" }), "not-an-email")).toEqual({ code: "email" });
    expect(validateField(field({ kind: "email" }), "a@b.co")).toBeNull();
    expect(validateField(field({ kind: "tel" }), "call me")).toEqual({ code: "phone" });
    expect(validateField(field({ kind: "tel" }), "+33 1 84 00 00 00")).toBeNull();
    expect(validateField(field({ kind: "date" }), "2026-13-45")).toEqual({ code: "date" });
    expect(validateField(field({ kind: "date" }), "2026-12-01")).toBeNull();
    expect(validateField(field({ kind: "select", options: ["a", "b"] }), "c")).toEqual({ code: "option" });
    expect(validateField(field({ kind: "select", options: ["a", "b"] }), "b")).toBeNull();
  });
});

describe("validateForm", () => {
  const fields = [field({ name: "full_name", required: true }), field({ name: "email", kind: "email" })];

  it("collects errors per field and requires consent", () => {
    const errors = validateForm(fields, { full_name: "", email: "x" }, false);
    expect(Object.keys(errors)).toEqual(["full_name", "email", "consent"]);
  });

  it("is empty for a valid submission", () => {
    expect(validateForm(fields, { full_name: "Salma Idrissi", email: "" }, true)).toEqual({});
  });
});

describe("buildAppointmentBody", () => {
  it("trims values, drops empty optionals, and only keeps declared fields", () => {
    const fields = [field({ name: "full_name", required: true }), field({ name: "email" }), field({ name: "reason" })];
    const body = buildAppointmentBody(fields, { full_name: "  Salma ", email: "", reason: "Check-up", injected: "x" }, true);
    expect(body).toEqual({ full_name: "Salma", reason: "Check-up", consent: true });
  });
});
