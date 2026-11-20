import "../globals.css";
import type { Metadata, Viewport } from "next";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { directionOf, routing } from "@/i18n/routing";
import { SITE_URL } from "@/lib/site";
import { arabicFont, latinFont } from "../fonts";

interface LocaleLayoutProps {
  readonly children: ReactNode;
  readonly params: Promise<{ locale: string }>;
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fbf9" },
    { media: "(prefers-color-scheme: dark)", color: "#0a110f" },
  ],
};

export async function generateMetadata({ params }: Omit<LocaleLayoutProps, "children">): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale });
  return {
    metadataBase: SITE_URL,
    title: { default: t("Meta.title"), template: `%s | ${t("Common.brand")}` },
    description: t("Meta.description"),
    applicationName: "Ausculta",
    referrer: "no-referrer",
    formatDetection: { telephone: false, email: false, address: false },
    icons: {
      icon: [
        { url: "/favicon.ico", sizes: "48x48" },
        { url: "/brand/ausculta-favicon.svg", type: "image/svg+xml" },
      ],
      apple: [{ url: "/brand/ausculta-app-icon-180.png", sizes: "180x180" }],
    },
    openGraph: {
      type: "website",
      siteName: "Ausculta",
      title: t("Meta.title"),
      description: t("Meta.description"),
      locale,
      images: [{ url: "/brand/ausculta-og.png", width: 1200, height: 630, alt: t("Common.tagline") }],
    },
    twitter: { card: "summary_large_image", images: ["/brand/ausculta-og.png"] },
    manifest: "/manifest.webmanifest",
    robots: { index: false, follow: false },
  };
}

export default async function LocaleLayout({ children, params }: LocaleLayoutProps) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  // Reading the request headers makes every page dynamic, which per-request CSP nonces require.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  const t = await getTranslations({ locale, namespace: "Common" });
  const messages = await getMessages({ locale });

  return (
    <html
      lang={locale}
      dir={directionOf(locale)}
      className={`${latinFont.variable} ${arabicFont.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* eslint-disable-next-line @next/next/no-sync-scripts -- must run before first paint to avoid a theme flash */}
        <script src="/theme-init.js" nonce={nonce} />
      </head>
      <body className="bg-bg text-ink antialiased">
        <a href="#main" className="skip-link">
          {t("skipToContent")}
        </a>
        {/* Locale context for client components (next-intl <Link>). Only the error page's messages are
            serialised here, for [locale]/error.tsx (a client boundary outside each page's own provider).
            Pages that render translated client islands nest their own provider with the namespaces they need. */}
        <NextIntlClientProvider locale={locale} messages={{ ErrorPage: messages.ErrorPage }} timeZone="UTC">
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
