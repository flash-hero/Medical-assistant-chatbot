#!/usr/bin/env node
/**
 * Serve the production build exactly as deploy/web.Dockerfile does: the standalone server with
 * .next/static and public/ copied next to it. (`next start` warns that it does not support
 * `output: "standalone"`.) Usage: node scripts/e2e/serve-standalone.mjs [--port 3100]
 */
import { spawn } from "node:child_process";
import { argValue, prepareStandalone } from "../measure/lib.mjs";

const PORT = argValue("port", process.env.PORT ?? "3100");

let prepared;
try {
  prepared = prepareStandalone(PORT);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}

const child = spawn(prepared.command, prepared.args, { ...prepared.options, stdio: "inherit" });

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
