/**
 * Shared helpers for the measurement scripts: atomic JSON writes, and starting the production build
 * (standalone server) in front of the mock API when they are not already running.
 */
import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";

export const WEB_ROOT = fileURLToPath(new URL("../../", import.meta.url));
export const MEASURE_DIR = `${WEB_ROOT}test-results/measure/`;
export const MOCK_PORT = Number(process.env.MOCK_API_PORT ?? 4010);
const WAIT_STEP_MS = 250;

/** Write JSON through a temp file and rename, so readers never see a half-written file. */
export function writeJsonAtomic(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(tmp, path);
}

export function argValue(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

async function isUp(url) {
  try {
    const response = await fetch(url, { redirect: "manual" });
    return response.status < 500;
  } catch {
    return false;
  }
}

export async function waitFor(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isUp(url)) return;
    await sleep(WAIT_STEP_MS);
  }
  throw new Error(`timed out waiting for ${url}`);
}

const STANDALONE = `${WEB_ROOT}.next/standalone/`;

/**
 * Lay the standalone build out as deploy/web.Dockerfile does (.next/static and public/ copied next
 * to server.js) and return the spawn arguments for it. Throws when there is no standalone build.
 */
export function prepareStandalone(port) {
  if (!existsSync(`${STANDALONE}server.js`)) throw new Error("No standalone build found. Run: npm run build");
  for (const [from, to] of [
    [`${WEB_ROOT}.next/static`, `${STANDALONE}.next/static`],
    [`${WEB_ROOT}public`, `${STANDALONE}public`],
  ]) {
    rmSync(to, { recursive: true, force: true });
    cpSync(from, to, { recursive: true });
  }
  const env = { ...process.env, NODE_ENV: "production", PORT: String(port), HOSTNAME: "127.0.0.1", NEXT_TELEMETRY_DISABLED: "1" };
  return { command: process.execPath, args: ["server.js"], options: { cwd: STANDALONE, env } };
}

/**
 * Ensure the mock API and the standalone production server are listening. Returns the base URL and
 * a stop() that only stops the processes this call started (each is a direct child, so kill() works
 * on Windows too, where signals are not delivered to grandchildren).
 */
export async function ensureServers(webPort) {
  const base = `http://127.0.0.1:${webPort}`;
  const started = [];
  const mockHealth = `http://127.0.0.1:${MOCK_PORT}/api/v1/health`;
  if (!(await isUp(mockHealth))) {
    const env = { ...process.env, MOCK_API_PORT: String(MOCK_PORT) };
    started.push(spawn(process.execPath, ["e2e/mock-api/server.mjs"], { cwd: WEB_ROOT, stdio: "ignore", env }));
    await waitFor(mockHealth, 30_000);
  }
  if (!(await isUp(`${base}/en`))) {
    const { command, args, options } = prepareStandalone(webPort);
    started.push(spawn(command, args, { ...options, stdio: "ignore" }));
    await waitFor(`${base}/en`, 120_000);
  }
  const stop = () => {
    for (const child of started) child.kill();
  };
  return { base, stop };
}
