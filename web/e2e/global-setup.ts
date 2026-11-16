import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));

/** Fail fast with instructions when the production build is missing or does not proxy to the mock API. */
export default function globalSetup(): void {
  const mockPort = process.env.MOCK_API_PORT ?? "4010";
  const manifest = `${ROOT}.next/routes-manifest.json`;
  if (!existsSync(`${ROOT}.next/BUILD_ID`) || !existsSync(manifest) || !existsSync(`${ROOT}.next/standalone/server.js`)) {
    throw new Error(`No production build. Run: API_ORIGIN=http://127.0.0.1:${mockPort} npm run build`);
  }
  const routes = readFileSync(manifest, "utf8");
  if (!routes.includes(`127.0.0.1:${mockPort}`)) {
    throw new Error(`The build proxies /api elsewhere. Rebuild with API_ORIGIN=http://127.0.0.1:${mockPort}`);
  }
}
