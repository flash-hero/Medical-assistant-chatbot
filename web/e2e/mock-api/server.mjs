#!/usr/bin/env node
/**
 * Mock Ausculta API for E2E tests and local UI work (docs/contracts/api.md). No dependencies.
 * Chat scenarios are selected by keywords in the message (see scenarios.mjs).
 *
 *   node e2e/mock-api/server.mjs            # listens on 127.0.0.1:4010 (MOCK_API_PORT to change)
 *
 * Test hooks (not part of the contract): GET /__mock/turns/<client_turn_id> reports whether the
 * client closed that turn's stream, so the E2E suite can assert that Stop really closes the connection.
 */
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { setTimeout as sleep } from "node:timers/promises";
import { publicHospital, RELEASE } from "./fixtures.mjs";
import { appointmentConfirmation, validateAppointment } from "./form-scenario.mjs";
import { buildScript, detectLanguage, pickScenario } from "./scenarios.mjs";

const PORT = Number.parseInt(process.env.MOCK_API_PORT ?? "4010", 10);
const HOST = process.env.MOCK_API_HOST ?? "127.0.0.1";
const LOCALES = new Set(["en", "fr", "ar"]);
const MAX_BODY_BYTES = 16 * 1024;
const TURNS_PER_SESSION = 20;
const KEEPALIVE_MS = 15_000;
const SLOW_STREAM_MAX_TICKS = 150;

const sessions = new Map(); // token -> { sessionId, locale, turnsLeft }
const turns = new Map(); // client_turn_id -> { scenario, startedAt, completed, closedByClient, closedAt }

class HttpError extends Error {
  constructor(status, code, message, retry = null) {
    super(message);
    Object.assign(this, { status, code, retry });
  }
}

function sendJson(res, status, body, headers = {}) {
  const data = body === null ? "" : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers });
  res.end(data);
}

function sendError(res, error) {
  const retryHeader = error.retry === null ? {} : { "retry-after": String(error.retry) };
  sendJson(res, error.status, { error: { code: error.code, message: error.message, retry_after_s: error.retry } }, retryHeader);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new HttpError(413, "invalid_input", "Request body too large.");
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "null");
  } catch {
    throw new HttpError(400, "invalid_input", "Body is not valid JSON.");
  }
}

function authSession(req) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  const session = sessions.get(token);
  if (!session) throw new HttpError(401, "unauthorized", "Session expired.");
  return session;
}

function localeOf(value) {
  if (!LOCALES.has(value)) throw new HttpError(422, "invalid_input", "Unsupported locale.");
  return value;
}

async function createSession(req, res) {
  const body = await readJson(req);
  const locale = localeOf(body?.locale);
  const token = `mock.${randomUUID()}`;
  const session = { sessionId: randomUUID(), locale, turnsLeft: TURNS_PER_SESSION };
  sessions.set(token, session);
  const expiresAt = new Date(Date.now() + 2 * 3600 * 1000).toISOString();
  sendJson(res, 201, {
    session_token: token,
    session_id: session.sessionId,
    expires_at: expiresAt,
    turns_left: session.turnsLeft,
    hospital: publicHospital(locale),
    demo_mode: true,
  });
}

function writeEvent(res, { type, payload }) {
  res.write(`event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`);
}

function openStream(res) {
  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-store, no-transform",
    "x-accel-buffering": "no",
    connection: "keep-alive",
  });
  res.flushHeaders();
}

/** Play a script; resolves when finished or when the client goes away (signal aborted). */
async function play(res, events, signal) {
  for (const event of events) {
    if (event.delayMs > 0) await sleep(event.delayMs, undefined, { signal });
    writeEvent(res, event);
  }
}

async function playSlow(res, script, signal) {
  await play(res, script.head, signal);
  for (let i = 0; i < SLOW_STREAM_MAX_TICKS; i += 1) {
    const event = script.tick(i);
    await sleep(event.delayMs, undefined, { signal });
    writeEvent(res, event);
  }
}

function trackTurn(clientTurnId, scenario) {
  const record = { scenario, startedAt: Date.now(), completed: false, closedByClient: false, closedAt: null };
  turns.set(clientTurnId, record);
  return record;
}

function parseChatBody(body) {
  const message = typeof body?.message === "string" ? body.message : "";
  if (message.trim() === "" || message.length > 2000) throw new HttpError(422, "invalid_input", "Message must be 1 to 2000 characters.");
  const clientTurnId = typeof body.client_turn_id === "string" && body.client_turn_id.length <= 64 ? body.client_turn_id : null;
  if (!clientTurnId) throw new HttpError(422, "invalid_input", "client_turn_id is required.");
  return { message, locale: localeOf(body.locale), clientTurnId };
}

async function chat(req, res) {
  const session = authSession(req);
  const { message, locale, clientTurnId } = parseChatBody(await readJson(req));
  if (session.turnsLeft <= 0) throw new HttpError(429, "session_exhausted", "Question limit reached.");
  const scenario = pickScenario(message);
  // Like the server's classifier: answer in the question's language, else the UI locale.
  const language = detectLanguage(message) ?? locale;
  const ctx = { locale, language, turnId: randomUUID(), sessionId: session.sessionId, turnsLeft: session.turnsLeft - 1 };
  const script = buildScript(scenario, ctx);
  if (script.kind === "error") throw new HttpError(script.status, script.body.error.code, script.body.error.message, script.retry);
  if (script.kind === "raw") {
    // A reverse proxy's own error page: no JSON envelope (review T5).
    res.writeHead(script.status, { "content-type": script.contentType, "cache-control": "no-store" });
    res.end(script.body);
    return;
  }
  session.turnsLeft -= 1;
  await streamTurn(res, script, trackTurn(clientTurnId, scenario));
}

async function streamTurn(res, script, record) {
  const controller = new AbortController();
  res.on("close", () => {
    if (!res.writableFinished) {
      record.closedByClient = true;
      record.closedAt = Date.now();
    }
    controller.abort();
  });
  openStream(res);
  const keepAlive = setInterval(() => res.write(": keep-alive\n\n"), KEEPALIVE_MS);
  try {
    if (script.kind === "slow") await playSlow(res, script, controller.signal);
    else await play(res, script.events, controller.signal);
    record.completed = true;
    res.end();
  } catch (error) {
    if (error?.name !== "AbortError") throw error;
  } finally {
    clearInterval(keepAlive);
  }
}

async function appointments(req, res) {
  const session = authSession(req);
  const body = await readJson(req);
  const invalid = validateAppointment(body);
  if (invalid.length > 0) throw new HttpError(422, "invalid_input", `Invalid fields: ${invalid.join(", ")}`);
  const requestId = `REQ-${randomUUID().slice(0, 6).toUpperCase()}`;
  sendJson(res, 201, { request_id: requestId, message: appointmentConfirmation(session.locale) });
}

async function feedback(req, res) {
  authSession(req);
  const body = await readJson(req);
  const okRating = body?.rating === "up" || body?.rating === "down";
  const okReason = body?.reason === undefined || ["incorrect", "unsafe", "unhelpful", "other"].includes(body.reason);
  const okComment = body?.comment === undefined || (typeof body.comment === "string" && body.comment.length <= 500);
  if (typeof body?.turn_id !== "string" || !okRating || !okReason || !okComment) throw new HttpError(422, "invalid_input", "Invalid feedback.");
  sendJson(res, 204, null);
}

function hospital(url, res) {
  const locale = LOCALES.has(url.searchParams.get("locale")) ? url.searchParams.get("locale") : "en";
  sendJson(res, 200, publicHospital(locale));
}

function turnStatus(url, res) {
  const id = decodeURIComponent(url.pathname.slice("/__mock/turns/".length));
  const record = turns.get(id);
  if (!record) throw new HttpError(404, "not_found", "Unknown turn.");
  sendJson(res, 200, record);
}

const ROUTES = {
  "GET /api/v1/health": (_req, res) => sendJson(res, 200, { status: "ok" }),
  "GET /api/v1/ready": (_req, res) => sendJson(res, 200, { status: "ready" }),
  "GET /api/v1/meta": (_req, res) => sendJson(res, 200, { ...RELEASE, demo_mode: true }),
  "GET /api/v1/hospital": (_req, res, url) => hospital(url, res),
  "POST /api/v1/session": createSession,
  "POST /api/v1/chat": chat,
  "POST /api/v1/appointments": appointments,
  "POST /api/v1/feedback": feedback,
};

async function handle(req, res) {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  try {
    if (req.method === "GET" && url.pathname.startsWith("/__mock/turns/")) return turnStatus(url, res);
    const route = ROUTES[`${req.method} ${url.pathname}`];
    if (!route) throw new HttpError(404, "not_found", "No such endpoint.");
    await route(req, res, url);
  } catch (error) {
    if (res.headersSent) {
      res.destroy();
      return;
    }
    sendError(res, error instanceof HttpError ? error : new HttpError(500, "internal", "Mock server error."));
    if (!(error instanceof HttpError)) console.error(error);
  }
}

const server = createServer((req, res) => void handle(req, res));
server.listen(PORT, HOST, () => console.log(`mock API listening on http://${HOST}:${PORT}`));

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
