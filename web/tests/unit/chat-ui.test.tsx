import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import LocaleError from "@/app/[locale]/error";
import { AppointmentForm } from "@/components/chat/AppointmentForm";
import { AssistantMessage } from "@/components/chat/AssistantMessage";
import { Composer } from "@/components/chat/Composer";
import { ErrorNotice } from "@/components/chat/ErrorNotice";
import { FeedbackBar } from "@/components/chat/FeedbackBar";
import { SafetyBanner } from "@/components/chat/SafetyBanner";
import { SourceDrawer } from "@/components/chat/SourceDrawer";
import { TurnView } from "@/components/chat/TurnView";
import { ApiError } from "@/lib/api/errors";
import type { FormEvent } from "@/lib/chat/types";
import { answer, citation, HOSPITAL, IntlWrapper, MESSAGES, reduceMotion, renderChat, safety, turn } from "./chat-render";

const en = MESSAGES.en.Chat;
const fr = MESSAGES.fr.Chat;
const ar = MESSAGES.ar.Chat;

beforeAll(() => {
  // jsdom has <dialog> without the modal API.
  const proto = HTMLDialogElement.prototype as { showModal?: () => void; close?: () => void };
  proto.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  proto.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  reduceMotion();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const form: FormEvent = {
  type: "form",
  form_id: "appointment_request",
  title: "Demander un rendez-vous",
  description: "Le personnel vous rappellera.",
  submit_url: "/api/v1/appointments",
  fields: [
    { name: "full_name", label: "Nom complet", kind: "text", required: true, options: [], max_length: 120 },
    { name: "phone", label: "Téléphone", kind: "tel", required: true, options: [], max_length: 32 },
    { name: "department_id", label: "Service", kind: "select", required: true, options: ["cardiology", "internal_medicine"], max_length: 200 },
    { name: "preferred_dates", label: "Dates souhaitées", kind: "textarea", required: true, options: [], max_length: 300 },
  ],
};

function fillForm(container: HTMLElement) {
  fireEvent.change(container.querySelector('[name="full_name"]')!, { target: { value: "Test Patient" } });
  fireEvent.change(container.querySelector('[name="phone"]')!, { target: { value: "+33 4 00 00 00 09" } });
  fireEvent.change(container.querySelector('[name="department_id"]')!, { target: { value: "cardiology" } });
  fireEvent.change(container.querySelector('[name="preferred_dates"]')!, { target: { value: "lundi matin" } });
  fireEvent.click(container.querySelector('input[name="consent"]')!);
}

describe("T1 language and direction of answer, question and safety text", () => {
  it("renders a French question on the Arabic UI left to right, in French", () => {
    renderChat(<TurnView turn={turn({ locale: "ar", question: "Que mesure le test HbA1c ?" })} />, { locale: "ar" });
    const bubble = screen.getByTestId("user-message");
    expect(bubble.getAttribute("lang")).toBe("fr");
    expect(bubble.getAttribute("dir")).toBe("ltr");
  });

  it("renders the answer in the language the server reports, not the UI locale", () => {
    const t = turn({ locale: "ar", answer: answer({ language: "fr", text: "Le test HbA1c mesure votre taux de sucre [1].\n\n- Votre médecin peut vous l’expliquer." }) });
    renderChat(<AssistantMessage turn={t} />, { locale: "ar" });
    const text = screen.getByTestId("answer-text");
    expect(text.getAttribute("lang")).toBe("fr");
    expect(text.getAttribute("dir")).toBe("ltr");
    for (const block of text.querySelectorAll("p, li")) expect(block.getAttribute("dir")).toBe("ltr");
  });

  it("detects an Arabic answer on the English UI and keeps a paragraph that starts with Latin letters RTL", () => {
    const t = turn({ locale: "en", answer: answer({ text: "HbA1c فحص يقيس متوسط مستوى السكر في الدم خلال الأشهر الثلاثة الماضية [1]." }) });
    renderChat(<AssistantMessage turn={t} />);
    const text = screen.getByTestId("answer-text");
    expect(text.getAttribute("lang")).toBe("ar");
    expect(text.querySelector("p")?.getAttribute("dir")).toBe("rtl");
  });

  it("opens a source with the answer's language, so the drawer compares the right languages", () => {
    const cited = citation(1, "en");
    const t = turn({ locale: "en", answer: answer({ language: "ar", text: "يقيس فحص HbA1c متوسط السكر [1].", citations: [cited] }) });
    const { actions } = renderChat(<AssistantMessage turn={t} />);
    fireEvent.click(screen.getByTestId("answer-text").querySelector("[data-cite]")!);
    expect(actions.openSource).toHaveBeenCalledWith(cited, "ar", expect.any(HTMLButtonElement));
  });

  it("shows the source-language note in the drawer when the source differs from the answer", () => {
    const source = { citation: citation(1, "en", { reviewed_on: "2025-09-12" }), answerLanguage: "fr" as const };
    const { rerender } = render(
      <IntlWrapper locale="ar">
        <SourceDrawer source={source} uiLocale="ar" onClose={() => undefined} />
      </IntlWrapper>,
    );
    expect(screen.getByTestId("source-language-note").textContent).toContain(ar.languageNames.en);
    rerender(
      <IntlWrapper locale="ar">
        <SourceDrawer source={{ ...source, answerLanguage: "en" }} uiLocale="ar" onClose={() => undefined} />
      </IntlWrapper>,
    );
    expect(screen.queryByTestId("source-language-note")).toBeNull();
  });

  it("gives safety text its own language and direction", () => {
    renderChat(<SafetyBanner safety={[safety("emergency", { language: "ar", title: "قد تكون هذه حالة طارئة", message: "اتصل بالطوارئ الآن." })]} hospital={HOSPITAL} />);
    const title = screen.getByRole("heading", { name: /حالة طارئة/ });
    expect(title.getAttribute("lang")).toBe("ar");
    expect(title.getAttribute("dir")).toBe("rtl");
  });
});

describe("T2 several safety events", () => {
  it("shows every kind, highest priority first, with merged contacts", () => {
    const events = [
      safety("emergency", { contacts: [{ label: "Emergency", number: "112", hours: "" }] }),
      safety("abuse_disclosure", { contacts: [{ label: "Violence line", number: "3919", hours: "" }, { label: "Emergency", number: "112", hours: "" }] }),
    ];
    renderChat(<SafetyBanner safety={events} hospital={HOSPITAL} />);
    const banner = screen.getByTestId("safety-banner");
    expect(banner.getAttribute("data-kind")).toBe("emergency");
    expect([...banner.querySelectorAll("[data-safety-kind]")].map((n) => n.getAttribute("data-safety-kind"))).toEqual(["emergency", "abuse_disclosure"]);
    expect([...banner.querySelectorAll('a[href^="tel:"]')].map((a) => a.getAttribute("href"))).toEqual(["tel:112", "tel:3919"]);
  });
});

describe("T3 department names in the appointment form", () => {
  it("labels department ids with the hospital's localised names", () => {
    const { container } = renderChat(<AppointmentForm turn={turn({ locale: "fr" })} form={form} />, { locale: "fr" });
    const options = [...container.querySelectorAll('select[name="department_id"] option')].map((o) => [o.getAttribute("value"), o.textContent]);
    expect(options).toEqual([
      ["", fr.form.chooseOption],
      ["cardiology", "Cardiologie"],
      ["internal_medicine", "Internal medicine"],
    ]);
  });
});

describe("T4 fallback safety banner", () => {
  it("uses localised text and the hospital's emergency number when the event carries neither", () => {
    renderChat(<SafetyBanner safety={[safety("emergency", { title: "", message: "", template_id: "" })]} hospital={HOSPITAL} />, { locale: "fr" });
    const banner = screen.getByTestId("safety-banner");
    expect(banner.textContent).toContain(fr.safetyFallback.title);
    expect(banner.textContent).toContain(fr.safetyFallback.message);
    expect(banner.querySelector('a[href="tel:112"]')).not.toBeNull();
  });

  it("tells the patient to call the local emergency number when no number is known", () => {
    renderChat(<SafetyBanner safety={[safety("emergency", { title: "", message: "" })]} hospital={null} />);
    expect(screen.getByTestId("safety-banner").textContent).toContain(en.safetyFallback.noNumber);
  });
});

describe("T5 error codes are never shown to patients", () => {
  it("shows the localised fallback for an unknown code without a server message", () => {
    renderChat(<ErrorNotice error={{ code: "http_502", message: "", retryAfterS: null }} onRetry={() => undefined} onNewConversation={() => undefined} />);
    const notice = screen.getByTestId("turn-error");
    expect(notice.textContent).toContain(en.errors.unknown);
    expect(notice.textContent).not.toContain("http_502");
  });

  it("T10/T15: has its own text for a silent stream and for a turn without an answer", () => {
    const { rerenderChat } = renderChat(<ErrorNotice error={{ code: "timeout", message: "", retryAfterS: null }} onRetry={() => undefined} onNewConversation={() => undefined} />);
    expect(screen.getByTestId("turn-error").textContent).toContain(en.errors.timeout);
    rerenderChat(<ErrorNotice error={{ code: "no_answer", message: "", retryAfterS: null }} onRetry={() => undefined} onNewConversation={() => undefined} />);
    expect(screen.getByTestId("turn-error").textContent).toContain(en.errors.no_answer);
  });
});

describe("T7 source-language badge", () => {
  it("names the languages the sources are really in", () => {
    const t = turn({ answer: answer({ language: "en", citations: [citation(1, "en"), citation(2, "fr")] }) });
    renderChat(<AssistantMessage turn={t} />);
    expect(screen.getByTestId("source-language-badge").textContent).toBe("Some sources for this answer are in French.");
  });

  it("lists several languages in the UI language", () => {
    const t = turn({ locale: "ar", answer: answer({ language: "ar", text: "نص [1] [2].", citations: [citation(1, "en"), citation(2, "es")] }) });
    renderChat(<AssistantMessage turn={t} />, { locale: "ar" });
    const badge = screen.getByTestId("source-language-badge").textContent ?? "";
    expect(badge).toContain(ar.languageNames.en);
    expect(badge).toContain(ar.languageNames.es);
  });

  it("is absent when every source is in the answer's language", () => {
    renderChat(<AssistantMessage turn={turn({ answer: answer({ language: "en", citations: [citation(1, "en")] }) })} />);
    expect(screen.queryByTestId("source-language-badge")).toBeNull();
  });
});

describe("T8 focus and announcements", () => {
  it("moves focus from Stop to the message box when Stop disappears", () => {
    const props = { inputRef: { current: null }, ready: true, turnsLeft: 5, onSend: () => true, onStop: () => undefined };
    const { rerenderChat } = renderChat(<Composer {...props} active />);
    const stop = screen.getByTestId("stop-button");
    stop.focus();
    rerenderChat(<Composer {...props} active={false} />);
    expect(document.activeElement).toBe(screen.getByTestId("composer-input"));
  });

  it("does not steal focus when the answer ends while the reader is elsewhere", () => {
    const props = { inputRef: { current: null }, ready: true, turnsLeft: 5, onSend: () => true, onStop: () => undefined };
    const { rerenderChat } = renderChat(<Composer {...props} active />);
    rerenderChat(<Composer {...props} active={false} />);
    expect(document.activeElement).toBe(document.body);
  });

  it("focuses the thank-you message after feedback is sent", async () => {
    renderChat(<FeedbackBar turn={turn({ answer: answer() })} />);
    fireEvent.click(screen.getByRole("button", { name: en.feedback.up }));
    const thanks = await screen.findByText(en.feedback.thanks);
    expect(thanks.getAttribute("role")).toBe("status");
    expect(document.activeElement).toBe(thanks);
  });

  it("focuses the confirmation after the appointment request is sent", async () => {
    const t = turn({ locale: "fr", form });
    const { container, rerenderChat } = renderChat(<AppointmentForm turn={t} form={form} />, { locale: "fr" });
    fillForm(container);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: fr.form.submit }));
    });
    rerenderChat(<AppointmentForm turn={{ ...t, formResult: { requestId: "REQ-1", message: "Merci." } }} form={form} />);
    expect(document.activeElement).toBe(screen.getByTestId("appointment-success"));
  });

  it("announces the stopped note", () => {
    renderChat(<AssistantMessage turn={turn({ phase: "stopped", streamed: "Partial text." })} />);
    expect(screen.getByTestId("stopped-note").getAttribute("role")).toBe("status");
  });
});

describe("T9 incomplete, unverified text", () => {
  it("labels streamed text left without a confirmed answer", () => {
    renderChat(<AssistantMessage turn={turn({ phase: "error", streamed: "Partial text.", error: { code: "upstream_error", message: "", retryAfterS: null } })} />);
    expect(screen.getByTestId("incomplete-note").textContent).toBe(en.incomplete);
  });

  it("labels a stopped stream too, and says nothing once an answer is confirmed", () => {
    const { rerenderChat } = renderChat(<AssistantMessage turn={turn({ phase: "stopped", streamed: "Partial text." })} />);
    expect(screen.getByTestId("incomplete-note")).toBeTruthy();
    rerenderChat(<AssistantMessage turn={turn({ phase: "done", streamed: "Text.", answer: answer({ text: "Text." }) })} />);
    expect(screen.queryByTestId("incomplete-note")).toBeNull();
  });
});

describe("T11 error boundary", () => {
  it("shows a localised page with the hospital's emergency contact and a retry", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "demo", name: "Demo", emergency: { label: "Urgences", number: "15" }, crisis_lines: [{ label: "Prévention du suicide", number: "3114" }] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const retry = vi.fn();
    render(
      <IntlWrapper locale="fr">
        <LocaleError error={new Error("boom")} retry={retry} />
      </IntlWrapper>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(MESSAGES.fr.ErrorPage.title);
    await waitFor(() => expect(document.querySelector('a[href="tel:15"]')).not.toBeNull());
    expect(document.querySelector('a[href="tel:3114"]')).not.toBeNull();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/hospital?locale=fr");
    fireEvent.click(screen.getByRole("button", { name: MESSAGES.fr.ErrorPage.retry }));
    expect(retry).toHaveBeenCalled();
  });

  it("still tells the patient what to do in an emergency when the profile is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(
      <IntlWrapper locale="ar">
        <LocaleError error={new Error("boom")} retry={() => undefined} />
      </IntlWrapper>,
    );
    expect(await screen.findByText(MESSAGES.ar.ErrorPage.emergencyNoNumber)).toBeTruthy();
  });

  it("does not crash the drawer on a date it cannot format", () => {
    const source = { citation: citation(1, "en", { reviewed_on: "2025-13-45" }), answerLanguage: "en" as const };
    render(
      <IntlWrapper locale="en">
        <SourceDrawer source={source} uiLocale="en" onClose={() => undefined} />
      </IntlWrapper>,
    );
    expect(screen.getByTestId("source-title")).toBeTruthy();
    expect(screen.queryByText(/Reviewed/)).toBeNull();
  });
});

describe("T13 non-sticky safety events", () => {
  it("renders them inside their turn", () => {
    const t = turn({ safety: [safety("harm_to_others", { sticky: false, title: "Keep everyone safe" }), safety("emergency")], answer: answer() });
    renderChat(<AssistantMessage turn={t} />);
    const inline = screen.getByTestId("turn-safety");
    expect(within(inline).getByRole("heading").textContent).toContain("Keep everyone safe");
    expect(inline.querySelectorAll("[data-safety-kind]")).toHaveLength(1);
  });
});

describe("T14 appointment submission", () => {
  it("explains a server refusal by its code and reuses the idempotency key for the same request", async () => {
    const submitForm = vi.fn().mockRejectedValueOnce(new ApiError("invalid_input", 422, "Invalid")).mockRejectedValueOnce(new ApiError("network", 0));
    const t = turn({ locale: "fr", form });
    const { container } = renderChat(<AppointmentForm turn={t} form={form} />, { locale: "fr", actions: { submitForm } });
    fillForm(container);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: fr.form.submit }));
    });
    expect(container.textContent).toContain(fr.form.errors.invalid_input);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: fr.form.submit }));
    });
    expect(container.textContent).toContain(fr.form.errors.network);
    const [first, second] = submitForm.mock.calls;
    expect(first?.[2]).toEqual(expect.any(String));
    expect(second?.[2]).toBe(first?.[2]);
  });

  it("uses a new key once the patient changes the request", async () => {
    const submitForm = vi.fn().mockRejectedValue(new ApiError("network", 0));
    const t = turn({ locale: "fr", form });
    const { container } = renderChat(<AppointmentForm turn={t} form={form} />, { locale: "fr", actions: { submitForm } });
    fillForm(container);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: fr.form.submit }));
    });
    fireEvent.change(container.querySelector('[name="phone"]')!, { target: { value: "+33 4 00 00 00 10" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: fr.form.submit }));
    });
    const [first, second] = submitForm.mock.calls;
    expect(second?.[2]).not.toBe(first?.[2]);
  });
});

describe("T18 composer, counters and health text fields", () => {
  const props = { inputRef: { current: null }, active: false, turnsLeft: 5, onSend: () => true, onStop: () => undefined };

  it("says why a message cannot be sent instead of doing nothing", () => {
    const { rerenderChat } = renderChat(<Composer {...props} ready={false} />);
    const input = screen.getByTestId("composer-input");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("send-blocked").textContent).toBe(en.sendBlocked.connecting);
    rerenderChat(<Composer {...props} ready turnsLeft={0} />);
    fireEvent.keyDown(screen.getByTestId("composer-input"), { key: "Enter" });
    expect(screen.getByTestId("send-blocked").textContent).toBe(en.sendBlocked.exhausted);
  });

  it("keeps browser spell-check services away from health text", async () => {
    const { container } = renderChat(<Composer {...props} ready />);
    expect(screen.getByTestId("composer-input").getAttribute("spellcheck")).toBe("false");
    const formView = renderChat(<AppointmentForm turn={turn({ form })} form={form} />);
    for (const field of formView.container.querySelectorAll("input[type=text], textarea")) expect(field.getAttribute("spellcheck")).toBe("false");
    const feedback = renderChat(<FeedbackBar turn={turn({ answer: answer() })} />);
    fireEvent.click(within(feedback.container).getByRole("button", { name: en.feedback.down }));
    expect(feedback.container.querySelector("textarea")?.getAttribute("spellcheck")).toBe("false");
    expect(container).toBeTruthy();
  });
});

describe("T1 citation buttons inside a foreign-language answer", () => {
  it("keep the UI language for their label", () => {
    const t = turn({ locale: "en", answer: answer({ language: "fr", text: "Le test HbA1c mesure le sucre [1].", citations: [citation(1, "en")] }) });
    renderChat(<AssistantMessage turn={t} />);
    expect(screen.getByTestId("answer-text").querySelector("[data-cite]")?.getAttribute("lang")).toBe("en");
  });
});
