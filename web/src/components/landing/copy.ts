import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import type { PreviewCopy } from "./PreviewAnswer";

export async function previewCopy(locale: Locale): Promise<PreviewCopy> {
  const t = await getTranslations({ locale, namespace: "Landing" });
  const chat = await getTranslations({ locale, namespace: "Chat" });
  return {
    you: chat("you"),
    assistant: chat("assistant"),
    question: t("previewQuestion"),
    answer: t("previewAnswer"),
    verified: chat("verified"),
    sourcesHeading: chat("sourcesHeading"),
    sourceTitle: t("previewSourceTitle"),
    sourcePublisher: t("previewSourcePublisher"),
    sourceSnippet: t("previewSourceSnippet"),
    checking: chat("status.checking"),
    searching: chat("status.searching"),
  };
}
