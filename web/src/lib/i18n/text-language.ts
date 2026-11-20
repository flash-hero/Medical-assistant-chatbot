/**
 * Which language and direction a piece of text is written in, when the server did not say.
 *
 * The server answers in the language of the question, which may differ from the UI locale (French typed
 * on the Arabic page). Arabic is told apart by script; French and English by short function words.
 * Direction follows the dominant script rather than the first strong letter, so an Arabic sentence that
 * starts with "HbA1c" still reads right to left (review T1).
 */

export type TextLanguage = "en" | "fr" | "ar";

const ARABIC_LETTER = /[ؠ-يٮ-ۓەۮ-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-ﻼ]/g;
const LATIN_LETTER = /[A-Za-zÀ-ÖØ-öø-ɏ]/g;
const WORD = /[a-zà-ÿœæ]+(?:['’][a-zà-ÿœæ]+)?/g;
const FRENCH_ELISION = /^(?:l|d|qu|n|s|j|c|m|t)['’]/;
const FRENCH_LETTER = /[àâçèéêëîïôùûüÿœæ]/i;

/** Frequent words that exist in one of the two languages only (no "on", "a", "me", "son", "plus"). */
const FRENCH_WORDS = new Set([
  "le", "la", "les", "des", "du", "de", "une", "un", "et", "est", "sont", "pour", "avec", "dans", "sur", "pas",
  "vous", "votre", "vos", "nous", "qui", "que", "quoi", "au", "aux", "il", "elle", "ce", "cette", "ces", "ou",
  "peut", "mais", "très", "quel", "quelle", "quels", "quelles", "comment", "pourquoi", "mon", "ma", "mes", "je",
  "tu", "ne", "se", "sa", "ses", "leur", "leurs", "aussi", "chez", "sans", "sous", "entre", "faut", "puis",
  "être", "avoir", "fait", "sera", "celle", "celui",
]);
const ENGLISH_WORDS = new Set([
  "the", "of", "and", "to", "is", "are", "in", "for", "with", "you", "your", "it", "this", "that", "be", "can",
  "or", "by", "not", "if", "what", "how", "do", "does", "at", "from", "have", "has", "my", "i", "should", "when",
  "which", "who", "why", "will", "would", "there", "their", "they", "was", "were", "about", "take", "much",
  "many", "give", "please", "get", "an",
]);

function count(text: string, pattern: RegExp): number {
  return text.match(pattern)?.length ?? 0;
}

function latinLanguage(text: string): TextLanguage | null {
  let french = 0;
  let english = 0;
  for (const word of text.toLowerCase().match(WORD) ?? []) {
    if (FRENCH_ELISION.test(word) || FRENCH_WORDS.has(word)) french += 1;
    else if (ENGLISH_WORDS.has(word)) english += 1;
  }
  if (french > english) return "fr";
  if (english > french) return "en";
  return FRENCH_LETTER.test(text) ? "fr" : null;
}

/** "en" | "fr" | "ar", or null when the text carries no usable signal (numbers, acronyms). */
export function detectTextLanguage(text: string): TextLanguage | null {
  const arabic = count(text, ARABIC_LETTER);
  const latin = count(text, LATIN_LETTER);
  if (arabic === 0 && latin === 0) return null;
  if (arabic > latin) return "ar";
  return latinLanguage(text);
}

/** "rtl" when Arabic letters dominate, "ltr" when Latin ones do, null without letters (use dir="auto"). */
export function scriptDirection(text: string): "ltr" | "rtl" | null {
  const arabic = count(text, ARABIC_LETTER);
  const latin = count(text, LATIN_LETTER);
  if (arabic === 0 && latin === 0) return null;
  return arabic > latin ? "rtl" : "ltr";
}

/** The `dir` attribute for a block of text: its dominant script, or the browser's own "auto". */
export function dirOf(text: string): "ltr" | "rtl" | "auto" {
  return scriptDirection(text) ?? "auto";
}
