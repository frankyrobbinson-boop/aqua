/**
 * Inline SVG botanicals + a scattered DecorationLayer for the garden cards.
 *
 * Everything here is deterministic: shapes are pure SVG (no hooks), positions
 * are hardcoded, and the only motion is a gentle `Math.sin` sway keyed off the
 * current frame (NO Math.random / Date.now), so renders cache and the MP4
 * matches the <Player> preview frame-for-frame. Colors derive from
 * `palette.accent` so decorations stay cohesive with any palette.
 */
import { useCurrentFrame, useVideoConfig } from "remotion";

import { darken, lighten } from "./theme";
import type {
  CardPalette,
  DecorationDensity,
  DecorationSet,
} from "./types";

type ShapeProps = { palette: CardPalette; size: number };

// --- individual botanicals (pure SVG) -------------------------------------

export function Leaf({ palette, size }: ShapeProps) {
  const fill = palette.accent;
  const vein = darken(palette.accent, 0.28);
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      <path
        d="M50 6 C80 26 80 70 50 96 C20 70 20 26 50 6 Z"
        fill={fill}
      />
      <path
        d="M50 14 L50 88"
        stroke={vein}
        strokeWidth={3}
        strokeLinecap="round"
      />
      <path
        d="M50 40 L34 30 M50 40 L66 30 M50 58 L34 48 M50 58 L66 48"
        stroke={vein}
        strokeWidth={2}
        strokeLinecap="round"
        fill="none"
        opacity={0.7}
      />
    </svg>
  );
}

export function Sprig({ palette, size }: ShapeProps) {
  const stem = darken(palette.accent, 0.18);
  const leaf = palette.accent;
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      <path
        d="M50 96 C48 70 52 50 50 10"
        stroke={stem}
        strokeWidth={4}
        fill="none"
        strokeLinecap="round"
      />
      <ellipse cx={38} cy={64} rx={13} ry={7} fill={leaf} transform="rotate(-35 38 64)" />
      <ellipse cx={62} cy={54} rx={13} ry={7} fill={leaf} transform="rotate(35 62 54)" />
      <ellipse cx={40} cy={42} rx={11} ry={6} fill={leaf} transform="rotate(-30 40 42)" />
      <ellipse cx={60} cy={32} rx={11} ry={6} fill={leaf} transform="rotate(30 60 32)" />
      <ellipse cx={50} cy={16} rx={9} ry={6} fill={leaf} />
    </svg>
  );
}

export function Flower({ palette, size }: ShapeProps) {
  const petal = palette.accent;
  const center = lighten(palette.accent, 0.5);
  const ring = darken(palette.accent, 0.12);
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <ellipse
          key={i}
          cx={50}
          cy={26}
          rx={13}
          ry={22}
          fill={petal}
          transform={`rotate(${i * 72} 50 50)`}
        />
      ))}
      <circle cx={50} cy={50} r={13} fill={center} />
      <circle cx={50} cy={50} r={13} fill="none" stroke={ring} strokeWidth={2} />
    </svg>
  );
}

/** A broad, full leaf — rounder and fuller than `Leaf`, for lush backdrop
 *  foliage. Additive: does not alter the other shapes. Pure SVG. */
export function BroadLeaf({ palette, size }: ShapeProps) {
  const fill = palette.accent;
  const vein = darken(palette.accent, 0.28);
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      <path
        d="M50 5 C 75 19 90 38 88 59 C 86 82 67 95 50 96 C 33 95 14 82 12 59 C 10 38 25 19 50 5 Z"
        fill={fill}
      />
      <path d="M50 14 L50 90" stroke={vein} strokeWidth={3} strokeLinecap="round" />
      <path
        d="M50 40 L27 31 M50 40 L73 31 M50 58 L24 51 M50 58 L76 51 M50 74 L31 68 M50 74 L69 68"
        stroke={vein}
        strokeWidth={2}
        strokeLinecap="round"
        fill="none"
        opacity={0.7}
      />
    </svg>
  );
}

/** A soft flowering sprig — a small, rounded bloom atop a slender stem with a
 *  pair of leaves. Colored entirely from `palette.accent` (bright petals, a pale
 *  center, a deeper tone for stem + leaves) so it reads as one warm little
 *  flower. Additive; pure SVG. */
export function BerrySprig({ palette, size }: ShapeProps) {
  const stem = darken(palette.accent, 0.24);
  const leaf = darken(palette.accent, 0.14);
  const petal = palette.accent;
  const center = lighten(palette.accent, 0.5);
  const ring = darken(palette.accent, 0.12);
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      <path
        d="M50 97 C 48 80 52 64 50 50"
        stroke={stem}
        strokeWidth={4}
        fill="none"
        strokeLinecap="round"
      />
      <ellipse cx={39} cy={70} rx={11} ry={6} fill={leaf} transform="rotate(-40 39 70)" />
      <ellipse cx={61} cy={64} rx={11} ry={6} fill={leaf} transform="rotate(40 61 64)" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <ellipse
          key={i}
          cx={50}
          cy={16}
          rx={8.5}
          ry={13}
          fill={petal}
          transform={`rotate(${i * 60} 50 30)`}
        />
      ))}
      <circle cx={50} cy={30} r={9} fill={center} />
      <circle cx={50} cy={30} r={9} fill="none" stroke={ring} strokeWidth={2} />
    </svg>
  );
}

/** Corner vine art drawn for the TOP-LEFT corner. Callers mirror it for the
 *  other corners with scaleX / scaleY. Pure SVG — placement + sway live in the
 *  card that uses it. */
export function VineCorner({ palette, size }: ShapeProps) {
  const stem = darken(palette.accent, 0.18);
  const leaf = palette.accent;
  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      style={{ display: "block", overflow: "visible" }}
    >
      <path
        d="M16 16 C 22 62, 30 104, 46 150"
        stroke={stem}
        strokeWidth={5}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M16 16 C 62 22, 104 30, 150 46"
        stroke={stem}
        strokeWidth={5}
        fill="none"
        strokeLinecap="round"
      />
      <ellipse cx={30} cy={66} rx={16} ry={9} fill={leaf} transform="rotate(58 30 66)" />
      <ellipse cx={40} cy={112} rx={16} ry={9} fill={leaf} transform="rotate(48 40 112)" />
      <ellipse cx={66} cy={30} rx={16} ry={9} fill={leaf} transform="rotate(-32 66 30)" />
      <ellipse cx={112} cy={40} rx={16} ry={9} fill={leaf} transform="rotate(-42 112 40)" />
      <circle cx={16} cy={16} r={7} fill={leaf} />
    </svg>
  );
}

// --- scattered layer -------------------------------------------------------

type Slot = {
  left: number; // %
  top: number; // %
  size: number; // px
  rotate: number; // deg
  phase: number; // rad — offsets the sway so pieces don't move in unison
};

// Hardcoded positions that hug the edges to keep the center clear for text.
// Density slices the first N.
const SLOTS: readonly Slot[] = [
  { left: 8, top: 15, size: 120, rotate: -18, phase: 0.0 },
  { left: 88, top: 13, size: 104, rotate: 24, phase: 1.1 },
  { left: 13, top: 82, size: 132, rotate: 12, phase: 2.0 },
  { left: 85, top: 84, size: 112, rotate: -22, phase: 0.7 },
  { left: 50, top: 9, size: 88, rotate: 6, phase: 2.6 },
  { left: 6, top: 49, size: 92, rotate: -8, phase: 1.7 },
  { left: 94, top: 51, size: 96, rotate: 16, phase: 3.0 },
  { left: 50, top: 91, size: 90, rotate: -4, phase: 0.4 },
  { left: 23, top: 30, size: 74, rotate: 30, phase: 1.4 },
  { left: 77, top: 69, size: 78, rotate: -28, phase: 2.3 },
];

const DENSITY_COUNT: Record<DecorationDensity, number> = {
  none: 0,
  low: 3,
  med: 6,
  high: 10,
};

const SWAY_SPEED = 1.1; // rad per second
const SWAY_DEG = 4;
const FLOAT_PX = 8;

type ShapeKind = "leaf" | "sprig" | "flower";

function pickKind(set: DecorationSet, i: number): ShapeKind {
  if (set === "flowers") return "flower";
  if (set === "mixed") return (["flower", "leaf", "sprig"] as const)[i % 3];
  // "leaves" and any unknown value: alternate foliage.
  return i % 2 === 0 ? "leaf" : "sprig";
}

function Shape({ kind, palette, size }: { kind: ShapeKind } & ShapeProps) {
  if (kind === "flower") return <Flower palette={palette} size={size} />;
  if (kind === "sprig") return <Sprig palette={palette} size={size} />;
  return <Leaf palette={palette} size={size} />;
}

/**
 * Scattered botanicals behind the card content. `set` picks the shapes, `density`
 * picks how many. `set === "none"` renders nothing regardless of density.
 */
export function DecorationLayer({
  set,
  density,
  palette,
}: {
  set: DecorationSet;
  density: DecorationDensity;
  palette: CardPalette;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (set === "none") return null;
  const count = DENSITY_COUNT[density] ?? DENSITY_COUNT.low;
  if (count === 0) return null;

  const t = frame / fps;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {SLOTS.slice(0, count).map((slot, i) => {
        const sway = Math.sin(t * SWAY_SPEED + slot.phase) * SWAY_DEG;
        const floatY = Math.sin(t * SWAY_SPEED * 0.9 + slot.phase) * FLOAT_PX;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${slot.left}%`,
              top: `${slot.top}%`,
              opacity: 0.9,
              transform: `translate(-50%, -50%) translateY(${floatY}px) rotate(${
                slot.rotate + sway
              }deg)`,
            }}
          >
            <Shape kind={pickKind(set, i)} palette={palette} size={slot.size} />
          </div>
        );
      })}
    </div>
  );
}
