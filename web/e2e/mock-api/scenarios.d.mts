/** Types for scenarios.mjs (used by the unit tests that check the mock against the UI's validators). */
export type MockLocale = "en" | "fr" | "ar";

export interface ScenarioContext {
  /** The UI locale (POST /chat `locale`). */
  readonly locale: MockLocale;
  /** The question's language; answers are written in it. Defaults to `locale`. */
  readonly language?: MockLocale;
  readonly turnId: string;
  readonly sessionId: string;
  readonly turnsLeft: number;
}

export function pickScenario(message: string): string;
export function detectLanguage(message: string): MockLocale | null;
export function chunk(text: string, words?: number): string[];
export function buildScript(name: string, ctx: ScenarioContext): unknown;
