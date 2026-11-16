import type { Metadata } from "next";
import { hasLocale } from "next-intl";
import { notFound } from "next/navigation";
import { Faq } from "@/components/landing/Faq";
import { FrontDesk } from "@/components/landing/FrontDesk";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { LandingMotion } from "@/components/landing/motion/LandingMotion";
import { SafetyPrinciples } from "@/components/landing/SafetyPrinciples";
import { SourcesTrust } from "@/components/landing/SourcesTrust";
import { previewCopy } from "@/components/landing/copy";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import { routing } from "@/i18n/routing";
import { alternatesFor } from "@/lib/site";

interface PageProps {
  readonly params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return hasLocale(routing.locales, locale) ? { alternates: alternatesFor(locale, "/") } : {};
}

export default async function LandingPage({ params }: PageProps) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const copy = await previewCopy(locale);
  return (
    <>
      <SiteHeader locale={locale} path="/" />
      <main id="main" tabIndex={-1} className="outline-none">
        <Hero locale={locale} copy={copy} />
        <HowItWorks locale={locale} copy={copy} />
        <SafetyPrinciples locale={locale} />
        <SourcesTrust locale={locale} />
        <FrontDesk locale={locale} />
        <Faq locale={locale} />
      </main>
      <SiteFooter locale={locale} />
      <LandingMotion />
    </>
  );
}
