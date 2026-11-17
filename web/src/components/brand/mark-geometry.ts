/**
 * Ausculta mark, drawn on a 32 x 32 grid: a stethoscope chestpiece seen face-on (rim and diaphragm)
 * whose rim resolves into a speech-bubble tail at the lower left: listening, then conversation.
 * Pure data, shared by the React component and scripts/brand/build-brand.mjs.
 */

export const GRID = 32;
const CX = 16.5;
const CY = 14.5;
const RIM_OUTER = 12.5;
/** The tail leaves the rim between these angles (degrees, clockwise from +x, y pointing down). */
const TAIL_FROM = 158;
const TAIL_TO = 112;
const TAIL_TIP = { x: 2.5, y: 29.5 } as const;
/** Bottom edge: a near-horizontal sweep continuing the rim. Inner edge: concave, a soft hook. */
const BOTTOM_CONTROL = { x: 8.2, y: 29.2 } as const;
const INNER_CONTROL = { x: 6.6, y: 24.6 } as const;

function round(n: number): string {
  return String(Math.round(n * 100) / 100);
}

function polar(radius: number, degrees: number): { x: number; y: number } {
  const rad = (degrees * Math.PI) / 180;
  return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) };
}

function circlePath(r: number): string {
  const a = `${round(CX + r)} ${round(CY)}`;
  const b = `${round(CX - r)} ${round(CY)}`;
  return `M${a}A${r} ${r} 0 1 0 ${b}A${r} ${r} 0 1 0 ${a}Z`;
}

function rimWithTail(innerRadius: number): string {
  const start = polar(RIM_OUTER, TAIL_FROM);
  const end = polar(RIM_OUTER, TAIL_TO);
  return [
    `M${round(start.x)} ${round(start.y)}`,
    `A${RIM_OUTER} ${RIM_OUTER} 0 1 1 ${round(end.x)} ${round(end.y)}`,
    `Q${BOTTOM_CONTROL.x} ${BOTTOM_CONTROL.y} ${TAIL_TIP.x} ${TAIL_TIP.y}`,
    `Q${INNER_CONTROL.x} ${INNER_CONTROL.y} ${round(start.x)} ${round(start.y)}Z`,
    circlePath(innerRadius),
  ].join("");
}

/** Rim + tail as one even-odd shape (rim 3 units wide). */
export const RIM_PATH = rimWithTail(9.5);
/** Favicon variant: a heavier rim (3.75 units) that survives 16 px rasterisation. */
export const RIM_PATH_SMALL = rimWithTail(8.75);
/** The diaphragm. */
export const DOT = { cx: CX, cy: CY, r: 4.25 } as const;
export const DOT_SMALL = { cx: CX, cy: CY, r: 4.75 } as const;
/** Geometric centre of the chestpiece, for ripple animations around the mark. */
export const CENTER = { x: CX, y: CY, r: RIM_OUTER } as const;
