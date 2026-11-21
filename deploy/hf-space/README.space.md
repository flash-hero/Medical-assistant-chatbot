---
title: Ausculta
emoji: 🩺
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
startup_duration_timeout: 1h
pinned: false
short_description: Medical information and hospital front desk, EN/FR/AR (demo)
---

# Ausculta (demo)

Ausculta is a multilingual (English, French, Arabic including Darija) assistant for **general health information** from
public health sources, with citations, and for **hospital front-desk questions** (opening hours, departments,
appointment requests).

Created by **Oussama Tabakh**, AI and data science engineer.

> **Demo only, not for real patients.** It does not diagnose, judge urgency or give doses. In an emergency, call your
> local emergency number. The hospital shown is fictional.

- Source code: https://github.com/flash-hero/Medical-assistant-chatbot
- Answers: Gemini (free tier). Search: a local embedding model (EmbeddingGemma-300M) over 29,730 passages from U.S.
  public-domain health sources (MedlinePlus, NIH institutes, NCI PDQ, CDC, FDA drug labels), loaded from the
  `flash-hero/ausculta-corpus` dataset.
- Safety: emergency and self-harm messages are detected without the model and answered first with emergency and
  crisis numbers.

This free Space sleeps after 48 hours without visitors; the first visit after that takes a few minutes to start.
