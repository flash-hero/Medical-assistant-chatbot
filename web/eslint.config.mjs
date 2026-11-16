import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**", "coverage/**", "lighthouse/**", "motion-audit/**", "next-env.d.ts"],
  },
  {
    rules: {
      "no-console": ["error", { allow: ["warn", "error"] }],
      "react/no-danger": "error",
    },
  },
  {
    files: ["e2e/**", "scripts/**"],
    rules: { "no-console": "off" },
  },
];

export default config;
