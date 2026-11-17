/**
 * Content Security Policy for every HTML response. A fresh nonce per request (see src/proxy.ts);
 * Next.js reads the nonce from the request CSP header and stamps it on its own scripts and styles.
 * No third-party origin appears anywhere: fonts are self-hosted, the API is same-origin.
 */
export interface CspOptions {
  readonly nonce: string;
  readonly isDev: boolean;
}

export function buildCsp({ nonce, isDev }: CspOptions): string {
  if (!/^[A-Za-z0-9+/=_-]{16,}$/.test(nonce)) {
    throw new Error("CSP nonce must be at least 16 base64 characters");
  }
  const directives: ReadonlyArray<readonly [string, string]> = [
    ["default-src", "'self'"],
    ["script-src", `'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`],
    // React dev tooling injects unnonced <style>; production stays nonce-only.
    ["style-src", isDev ? "'self' 'unsafe-inline'" : `'self' 'nonce-${nonce}'`],
    ["img-src", "'self' data:"],
    ["font-src", "'self'"],
    ["connect-src", isDev ? "'self' ws:" : "'self'"],
    ["manifest-src", "'self'"],
    ["media-src", "'none'"],
    ["object-src", "'none'"],
    ["frame-src", "'none'"],
    ["worker-src", "'self'"],
    ["frame-ancestors", "'none'"],
    ["base-uri", "'none'"],
    ["form-action", "'self'"],
  ];
  return directives.map(([name, value]) => `${name} ${value}`).join("; ");
}

/** 128 bits from the platform CSPRNG, base64 encoded. */
export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
