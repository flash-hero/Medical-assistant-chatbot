/** Types for scenarios.mjs (used by the unit tests that check the mock against the UI's validators). */
export interface ScenarioContext {
  readonly locale: "en" | "fr" | "ar";
  readonly turnId: string;
  readonly sessionId: string;
  readonly turnsLeft: number;
}

export function pickScenario(message: string): string;
export function chunk(text: string, words?: number): string[];
export function buildScript(name: string, ctx: ScenarioContext): unknown;
