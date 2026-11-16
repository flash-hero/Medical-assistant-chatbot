import type { Metadata } from "next";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { ChatApp } from "@/components/chat/ChatApp";
import { routing } from "@/i18n/routing";
import { alternatesFor } from "@/lib/site";

interface PageProps {
  readonly params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "Meta" });
  return { title: t("chatTitle"), alternates: alternatesFor(locale, "/chat") };
}

export default async function ChatPage({ params }: PageProps) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const messages = await getMessages({ locale });
  // Motion injects a <style> element for popLayout exits; the CSP only admits it with this request's nonce.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  // Only the namespaces the chat island renders are serialised to the client.
  return (
    <NextIntlClientProvider locale={locale} timeZone="UTC" messages={{ Chat: messages.Chat, Common: messages.Common }}>
      <ChatApp locale={locale} nonce={nonce} />
    </NextIntlClientProvider>
  );
}
