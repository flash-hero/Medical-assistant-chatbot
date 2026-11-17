import "./globals.css";
import Link from "next/link";
import { latinFont, arabicFont } from "./fonts";

/** Fallback for paths outside any locale (the proxy normally redirects them to /en). */
export default function GlobalNotFound() {
  return (
    <html lang="en" className={`${latinFont.variable} ${arabicFont.variable}`}>
      <body className="grid min-h-dvh place-items-center bg-bg p-6 text-ink">
        <main className="grid max-w-md gap-4 text-center">
          <h1 className="text-3xl font-bold">This page does not exist</h1>
          <p className="text-ink-2">The link may be broken or the page may have moved.</p>
          <p>
            <Link className="btn btn-primary" href="/en">
              Go to the home page
            </Link>
          </p>
        </main>
      </body>
    </html>
  );
}
