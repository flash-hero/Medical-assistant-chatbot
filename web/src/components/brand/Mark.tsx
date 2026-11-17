import { DOT, DOT_SMALL, GRID, RIM_PATH, RIM_PATH_SMALL } from "./mark-geometry";

interface MarkProps {
  readonly size?: number;
  readonly className?: string;
  /** Accessible name; omit when the mark sits next to visible text (it is then decorative). */
  readonly title?: string;
  /** The heavier small-size drawing, for anything rendered at 24 px or less. */
  readonly small?: boolean;
  readonly ringClassName?: string;
}

/** The Ausculta mark in currentColor, so it follows the theme. */
export function Mark({ size = 32, className, title, small = false, ringClassName }: MarkProps) {
  const dot = small ? DOT_SMALL : DOT;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${GRID} ${GRID}`}
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      <path fill="currentColor" fillRule="evenodd" d={small ? RIM_PATH_SMALL : RIM_PATH} className={ringClassName} />
      <circle fill="currentColor" cx={dot.cx} cy={dot.cy} r={dot.r} />
    </svg>
  );
}
