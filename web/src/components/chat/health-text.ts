/**
 * Props for every free-text field that can hold health or personal details (review T18). Browser
 * "enhanced" spell-checkers and grammar extensions send typed text to remote services; these fields
 * opt out. The server still treats what it receives as sensitive.
 */
export const HEALTH_TEXT_PROPS = {
  spellCheck: false,
  autoCorrect: "off",
  "data-gramm": "false",
  "data-gramm_editor": "false",
  "data-enable-grammarly": "false",
} as const;
