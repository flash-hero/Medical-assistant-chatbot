import { Mark } from "./Mark";

interface LogoProps {
  /** The localised wordmark: "Ausculta" or "أوسكولتا". */
  readonly name: string;
  readonly size?: "sm" | "md";
}

/** Mark + live-text wordmark (the outlined SVG wordmarks in /public/brand are for use outside the app). */
export function Logo({ name, size = "md" }: LogoProps) {
  const markSize = size === "sm" ? 26 : 30;
  return (
    <span className="inline-flex items-center gap-2 text-brand">
      <Mark size={markSize} small />
      <span className={`font-bold tracking-[-0.01em] text-ink ${size === "sm" ? "text-lg" : "text-xl"}`}>{name}</span>
    </span>
  );
}
