# Ausculta: intended purpose statement

Status: **DRAFT, demo mode.** Real-patient use is blocked until every item in "Pilot gate" is signed.

## What Ausculta is

A conversational assistant that:

1. **Explains general health information** in plain language (English, French, Arabic), using only passages retrieved from a licence-checked corpus of public health sources, with dated citations.
2. **Helps people navigate a hospital**: departments, opening hours, contacts, directions, visiting rules, documents to bring, and an appointment *request* form whose contents go to hospital staff, never to the language model.
3. **Points people to the right level of care**: every medical answer includes general "when to seek care" guidance, and emergency or crisis messages trigger a fixed, pre-approved safety message with the hospital's verified emergency contacts.

## What Ausculta is not

- Not a diagnostic tool. It does not name what a person has, rank possible conditions, or estimate likelihoods.
- Not a triage device. It does not assign urgency levels, dispositions or severity scores to an individual.
- Not a prescriber. It does not give personal doses, calculate doses, or advise starting, stopping or changing a treatment.
- Not a substitute for a clinician, and not for use in clinical practice or to make clinical decisions.
- Not an emergency service.

## Why the boundary is strict

- The Gemini API Additional Terms prohibit use "in clinical practice, to provide medical advice, or in any manner that is overseen by or requires clearance or approval from a medical device regulatory agency".
- Software that gives individual diagnostic or therapeutic recommendations to patients is regulated as a medical device (EU MDR Rule 11, FDA device software functions). Ausculta's claims and behaviour are kept inside general information and navigation.
- EU AI Act Article 50 (applies since 2026-08-02): people must be told they are talking to an AI. The UI shows a persistent "AI assistant" label.

## Enforced in code (not only in prompts)

| Commitment | Enforcement |
|---|---|
| No diagnosis / triage verdict / personal dosing | Router intents, policy prompt, refusal evals (gate 98%+) |
| Emergency and self-harm handled first | Deterministic multilingual detector with no model dependency; template returns in < 300 ms even if every model call fails |
| Answers grounded in sources | Abstention on weak retrieval; citation validity 100%; numeric grounding for drug answers |
| Hospital facts never invented | Rendered only from the validated hospital profile; phone numbers allow-listed |
| Privacy | Deterministic redaction before any model call or log; no transcript text stored by default; `store=False` on Gemini |
| Licences respected | CI-enforced source registry; excluded sources can never be indexed |

## Pilot gate (P7, external; all required before `AUSCULTA_DEMO_MODE=false`)

- [ ] Legal review of the Gemini API terms for this use, or migration to Vertex AI under Google Cloud terms with a signed BAA/DPA as applicable
- [ ] Paid (billed) Gemini project; API key rotated and stored only in the server secret store
- [ ] Clinician sign-off on the emergency/self-harm lexicons, safety templates, and a 100-answer review per language
- [ ] Hospital-verified profile (departments, hours, phone numbers, emergency and crisis contacts) with a named verifier and date
- [ ] Data protection impact assessment (GDPR Art. 9 special-category data; local health-data hosting rules)
- [ ] Regulatory consultant confirms non-device status of the intended purpose and claims

Signed: ____________________  Date: __________
