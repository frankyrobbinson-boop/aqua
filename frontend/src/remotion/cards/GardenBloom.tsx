/**
 * GardenBloom — a warm, inviting garden title card where the garden itself IS
 * the design: no panel, no kicker. The title sits directly on a soft, sunlit
 * garden wash, framed by an ABUNDANT, LAYERED botanical composition that
 * "blooms in":
 *
 *   - A large, soft, blurred BACK layer of foliage forms a hazy wash behind
 *     everything; then a single pool of well-spaced FRONT anchors hugs the
 *     edges and corners, split so the crisp SVG botanicals and the optional
 *     Lottie animations never share a spot (even anchors → botanicals, odd →
 *     Lottie) — nothing piles up. The center stays clear for the text.
 *   - Every piece softly MATERIALIZES with a staggered settle — a small downward
 *     drift + fade with only a whisper of scale — from frame 0, back layer
 *     first, each easing ~0.7s on a soft decelerating cubic (Easing.out) at LOW
 *     velocity so nothing drops or pops; once in, it sways slowly and subtly
 *     forever (Math.sin), the sway easing on with the entrance so the settle
 *     blends seamlessly into the drift. Each piece's phase is blended toward a
 *     shared base, so the whole garden breathes TOGETHER — one soft breeze, not
 *     scattered bobbing. The optional Lottie animations materialize and sway the
 *     very same way, so the two decoration layers move together.
 *   - Foliage greens derive from `palette.text`, softer the further back a layer
 *     sits; blooms/berries + the optional `highlight` word use `palette.accent`
 *     (a warm floral rose by default). Fully recolorable via `palette`.
 *
 * The DECORATIONS establish first: they bloom in from frame 0, and only THEN —
 * ~0.95s in, via a delayed <Sequence> — does the title rise in (the shared soft
 * `useTextEntrance`, default "rise") into the garden, the subtitle fading in
 * just after.
 *
 * The whole opening BLOOMS UP FROM BLACK as ONE gesture: at frame 0 the stage
 * is pure black; over the first ~0.27s the garden gradient wash + the ambient
 * atmosphere EMERGE up from it (eased) at the very same time as the botanicals
 * begin to materialize — so a soft wash is already visible by ~0.15s (no early
 * black void) — and then, a beat later, the title rises. There is NO separate
 * uniform fade-in dimming the whole stage first; the emergence, the bloom, and
 * the title rise overlap into a single continuous motion, not a fade followed by
 * a bloom. Only the END keeps a soft whole-scene fade-OUT, so the beat departs
 * cleanly (and loops in the Player).
 *
 * On top of that, a few gentle layers make the card read as a warm MOMENT
 * inside a video rather than a still book cover — with NO zoom or pan anywhere:
 * (1) ambient ATMOSPHERE (drifting warm sun pools + floating motes, see
 * Atmosphere.tsx — fading up WITH the scene), (2) the botanicals' own
 * continuous, gentle sway/float, and (3) a balanced, centered composition — the
 * title centered, a few botanicals bleeding past the edges so the garden feels
 * bigger than the frame. The title itself is held STATIC for legibility (only
 * its one-time entrance rise remains) — no per-frame drift to stutter the crisp
 * type. All are additive and subtle. Everything is deterministic (frame-based
 * only; NO Math.random / Date.now) and siblings are imported by RELATIVE path
 * (no `@/*` alias in the Remotion bundle), so the <Player> preview matches the
 * MP4 render frame-for-frame.
 */
import { useMemo } from "react";
import { Lottie, type LottieAnimationData } from "@remotion/lottie";
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { useFadeIn, useTextEntrance } from "../animations";
import { AtmosphereLight, AtmosphereMotes } from "./Atmosphere";
import { Background } from "./Background";
import { BerrySprig, BroadLeaf, Flower, Leaf, Sprig } from "./decorations";
import { cloneLottie, isLikelyLottie, recolorLottie } from "./lottie";
import { mix, resolveFontFamily } from "./theme";
import type {
  CardDecoration,
  CardPalette,
  CardProps,
  DecorationDensity,
  DecorationSet,
  LottieDensity,
  LottieRuntimeEntry,
} from "./types";

// Frame-interpolate preset: a soft decelerating cubic (ease-OUT) so decorations
// gently MATERIALIZE — starting to appear quickly, then easing to a low-velocity
// landing rather than dropping/popping in — clamped both ends so values hold
// once the entrance ends.
const FLOW = {
  easing: Easing.out(Easing.cubic),
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

// Ambient life + entrance SHARED by the SVG botanicals and the Lottie layer, so
// the two decoration layers drift together. Amplitudes and frequencies are kept
// LOW so the settled garden breathes with a slow, subtle sway — one soft breeze,
// not lively bobbing. The decorations materialize in FIRST — from frame 0, each
// easing GENTLY over ~0.7s on a small downward settle — so the garden softly
// establishes before the title arrives. Deterministic (frame-based; no
// Math.random / Date.now).
const SWAY_DEG = 3; // rotate sway amplitude (deg) — subtle
const FLOAT_PX = 5; // vertical float amplitude (px) — subtle
const SWAY_FREQ = 0.45; // rotate sway speed (rad/s) — slow
const FLOAT_FREQ = 0.4; // vertical float speed (rad/s) — slow
const DECOR_ENTER_SECONDS = 0.7; // per-piece entrance duration — gentle materialize
const DECOR_DRIFT_PX = 14; // small downward settle on entrance — low velocity, no drop
// Cohesion: each piece's sway/float phase is blended TOWARD a shared base (0) by
// this factor, so the garden sways largely TOGETHER (one breeze) with only a
// touch of per-piece variation, instead of every piece on its own beat.
const SWAY_PHASE_SPREAD = 0.35;

// --- emergence + fade-out --------------------------------------------------

/** The scene EMERGES from black: the garden gradient wash + the ambient
 *  atmosphere fade up from the black stage over the first ~0.27s on the SAME
 *  soft ease-out cubic as the decoration bloom (FLOW), so the wash swells up in
 *  LOCKSTEP with the botanicals — one gesture, a bloom up from black, rather than
 *  a fast pre-fade that arrives before the bloom has started. Short + gentle: a
 *  soft wash is already visible by ~0.15s (no early black void), NOT a hard pop.
 *  The per-piece bloom + the title's rise carry their OWN entrances and are NOT
 *  dimmed by this. */
function useEmerge(): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const end = Math.max(1, Math.round(0.27 * fps));
  return interpolate(frame, [0, end], [0, 1], FLOW);
}

/** A soft whole-scene fade-OUT over the last ~0.5s so the beat departs cleanly
 *  (and loops in the Player). There is deliberately NO fade-IN — the entrance is
 *  the scene emerging from black (see useEmerge), not a uniform dim-then-pop. */
function useFadeOut(): number {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const outStart = Math.max(1, durationInFrames - Math.round(0.5 * fps));
  return interpolate(frame, [outStart, durationInFrames - 1], [1, 0], {
    easing: Easing.in(Easing.ease),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

/** Lowercase + strip surrounding punctuation, so a `highlight` of "Bloom"
 *  matches a title word "Bloom," or "Bloom". */
const normWord = (w: string): string =>
  w.toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");

// --- layered decoration ----------------------------------------------------

type BloomKind = "broadleaf" | "leaf" | "sprig" | "flower" | "berry";

type BloomSlot = {
  left: number; // %
  top: number; // %
  size: number; // px
  rotate: number; // deg (base tilt)
  phase: number; // rad (sway offset, so pieces don't move in unison)
  kind: BloomKind;
};

// The soft BACK wash: large foliage bleeding off the corners/edges, faded and
// blurred into a hazy backdrop that sits behind everything and never collides
// with the crisp foreground. Always on; ordered first so the index-based
// entrance stagger blooms the backdrop in before the FRONT anchors settle over
// it.
const BACK_SLOTS: readonly BloomSlot[] = [
  { left: 5, top: 6, size: 460, rotate: -18, phase: 0.0, kind: "broadleaf" },
  { left: 96, top: 9, size: 440, rotate: 22, phase: 1.1, kind: "broadleaf" },
  { left: 7, top: 97, size: 480, rotate: 14, phase: 2.0, kind: "broadleaf" },
  { left: 94, top: 95, size: 450, rotate: -24, phase: 0.7, kind: "broadleaf" },
  { left: 50, top: 0, size: 380, rotate: 4, phase: 2.6, kind: "leaf" },
  { left: 100, top: 52, size: 360, rotate: 92, phase: 1.7, kind: "broadleaf" },
  { left: 0, top: 50, size: 360, rotate: -92, phase: 3.0, kind: "broadleaf" },
];

// The FRAMING ANCHOR POOL — one shared set of well-spaced foreground positions,
// allocated so the crisp SVG botanicals and the Lottie animations NEVER share a
// spot: EVEN indices feed the SVG foreground, ODD indices feed the Lottie layer.
// Authored in interleaved FILL order — pair k is [SVG #k, Lottie #k] — and each
// system's picks hop across the frame, so taking the first N (by density) always
// reads balanced. The pool is BALANCED around center — the title is now
// CENTERED (see GardenBloom), so the decorations frame all four edges and
// corners SYMMETRICALLY (left↔right, top↔bottom) while the CENTER band is kept
// clear for the text, and a few of the larger corner anchors sit right on / past
// the frame edges so the garden bleeds off-screen and feels bigger than the
// frame. Every SVG anchor still sits well clear of every Lottie anchor, so the
// two layers never pile up.
//
// `size` is the SVG footprint in px; the Lottie layer draws its box at
// `size * LOTTIE_BOX_SCALE` (Lottie art carries transparent padding, so it needs
// a larger box to read at the same weight). `opacity` is the piece's depth —
// crisp up front (~0.95) to soft further back (~0.6).
type FrameAnchor = {
  left: number; // %
  top: number; // %
  size: number; // px — SVG footprint; Lottie box = size * LOTTIE_BOX_SCALE
  rotate: number; // deg — SVG base tilt (Lottie ignores)
  phase: number; // rad — SVG sway offset (Lottie ignores)
  kind: BloomKind; // SVG designed kind (Lottie ignores)
  opacity: number; // depth: ~0.6 (soft/back) .. ~0.96 (crisp/front)
};

const FRAME_ANCHORS: readonly FrameAnchor[] = [
  // pair 0 — SVG top-left corner (large, bleeds off TL) / Lottie top edge (left-of-center)
  { left: 6, top: 7, size: 240, rotate: -16, phase: 0.0, kind: "broadleaf", opacity: 0.8 },
  { left: 33, top: 7, size: 160, rotate: 0, phase: 0.4, kind: "leaf", opacity: 0.7 },
  // pair 1 — SVG bottom-right corner (large, bleeds off BR) / Lottie bottom edge (right-of-center)
  { left: 94, top: 93, size: 235, rotate: 18, phase: 1.1, kind: "berry", opacity: 0.9 },
  { left: 67, top: 93, size: 168, rotate: 0, phase: 1.3, kind: "flower", opacity: 0.82 },
  // pair 2 — SVG top-right corner (large, bleeds off TR) / Lottie top edge (right-of-center)
  { left: 94, top: 7, size: 245, rotate: 20, phase: 2.0, kind: "broadleaf", opacity: 0.82 },
  { left: 67, top: 7, size: 160, rotate: 0, phase: 2.2, kind: "leaf", opacity: 0.7 },
  // pair 3 — SVG bottom-left corner (large, bleeds off BL) / Lottie bottom edge (left-of-center)
  { left: 6, top: 93, size: 230, rotate: -18, phase: 0.7, kind: "berry", opacity: 0.9 },
  { left: 33, top: 93, size: 168, rotate: 0, phase: 0.9, kind: "flower", opacity: 0.82 },
  // pair 4 — SVG left-mid (edge) / Lottie bottom-center
  { left: 4, top: 50, size: 175, rotate: -22, phase: 1.7, kind: "sprig", opacity: 0.88 },
  { left: 50, top: 95, size: 158, rotate: 0, phase: 1.9, kind: "flower", opacity: 0.8 },
  // pair 5 — SVG right-mid (edge) / Lottie left edge (upper)
  { left: 96, top: 50, size: 175, rotate: 22, phase: 2.6, kind: "sprig", opacity: 0.88 },
  { left: 5, top: 28, size: 150, rotate: 0, phase: 2.8, kind: "leaf", opacity: 0.64 },
  // pair 6 — SVG top-center / Lottie right edge (lower)
  { left: 50, top: 5, size: 150, rotate: 4, phase: 3.1, kind: "flower", opacity: 0.94 },
  { left: 95, top: 72, size: 150, rotate: 0, phase: 0.5, kind: "leaf", opacity: 0.64 },
];

// The pool split into its two disjoint allotments (they never overlap): the
// crisp SVG foreground draws from the EVEN anchors, the Lottie layer from the
// ODD ones. Deterministic (index parity only — no Math.random / Date.now).
const SVG_ANCHORS: readonly FrameAnchor[] = FRAME_ANCHORS.filter(
  (_, i) => i % 2 === 0,
);
const LOTTIE_ANCHORS: readonly FrameAnchor[] = FRAME_ANCHORS.filter(
  (_, i) => i % 2 === 1,
);

// How many crisp SVG foreground botanicals to place, by `decoration.density`
// (capped at the SVG-allotted anchor count). The BACK wash is always on;
// `set === "none"` hides everything.
const SVG_FRONT_COUNT: Record<DecorationDensity, number> = {
  none: 0,
  low: 3,
  med: 5,
  high: 7,
};

// The BACK wash look: faded + blurred into a hazy depth backdrop. Its foliage
// green is mixed this far from `palette.text` toward the background — softer for
// the distant back, a touch deeper for the crisp foreground.
const BACK_STYLE = { opacity: 0.34, blur: 4, foliageMix: 0.4 };
const FRONT_FOLIAGE_MIX = 0.3;

// Lottie art carries transparent padding, so its box is scaled up from the
// shared anchor `size` to read at the same visual weight as an SVG botanical.
const LOTTIE_BOX_SCALE = 1.8;

/** Honor `set`: bias to blooms for "flowers", to foliage for "leaves", else use
 *  the slot's designed kind (the lush default blend). */
function resolveKind(
  set: DecorationSet,
  designed: BloomKind,
  i: number,
): BloomKind {
  const isBloom = designed === "flower" || designed === "berry";
  if (set === "flowers")
    return isBloom ? designed : i % 2 === 0 ? "flower" : "berry";
  if (set === "leaves")
    return isBloom ? (i % 2 === 0 ? "broadleaf" : "sprig") : designed;
  return designed; // "mixed" / unknown / default
}

function BloomPiece({
  kind,
  foliage,
  bloom,
  size,
}: {
  kind: BloomKind;
  foliage: CardPalette;
  bloom: CardPalette;
  size: number;
}) {
  switch (kind) {
    case "broadleaf":
      return <BroadLeaf palette={foliage} size={size} />;
    case "sprig":
      return <Sprig palette={foliage} size={size} />;
    case "flower":
      return <Flower palette={bloom} size={size} />;
    case "berry":
      return <BerrySprig palette={bloom} size={size} />;
    case "leaf":
    default:
      return <Leaf palette={foliage} size={size} />;
  }
}

function BloomDecor({
  palette,
  decoration,
}: {
  palette: CardPalette;
  decoration: CardDecoration;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  if (decoration.set === "none") return null;

  const frontCount =
    SVG_FRONT_COUNT[decoration.density] ?? SVG_FRONT_COUNT.high;

  // The always-on BACK wash, then the crisp SVG foreground drawn from its
  // allotted (even) anchors. Flattened to one list carrying each piece's look
  // (opacity/blur/foliage tint), ordered back → front so the entrance stagger
  // blooms the hazy backdrop in first.
  const pieces = [
    ...BACK_SLOTS.map((slot) => ({
      left: slot.left,
      top: slot.top,
      size: slot.size,
      rotate: slot.rotate,
      phase: slot.phase,
      kind: slot.kind,
      opacity: BACK_STYLE.opacity,
      blur: BACK_STYLE.blur,
      foliageMix: BACK_STYLE.foliageMix,
    })),
    ...SVG_ANCHORS.slice(0, frontCount).map((a) => ({
      left: a.left,
      top: a.top,
      size: a.size,
      rotate: a.rotate,
      phase: a.phase,
      kind: a.kind,
      opacity: a.opacity,
      blur: 0,
      foliageMix: FRONT_FOLIAGE_MIX,
    })),
  ];

  // Blooms/berries take the real accent (warm rose); foliage greens derive from
  // the deep text color, mixed per piece (BACK_STYLE vs FRONT_FOLIAGE_MIX).
  const bloom = palette;

  // Entrance: each piece softly MATERIALIZES — a small downward settle + fade,
  // with only a whisper of scale — staggered by index so the garden eases in
  // gently. Starts at frame 0 so the decorations lead the title.
  const startBase = 0;
  const stagger = 1; // frames between pieces — gentle cascade
  const enter = Math.round(DECOR_ENTER_SECONDS * fps); // gentle entrance per piece

  // One piece's entrance + endless sway. `i` is the flattened index (back wash
  // first, then crisp foreground) so the stagger blooms the backdrop in before
  // the foreground.
  const renderPiece = (piece: (typeof pieces)[number], i: number) => {
    const foliage: CardPalette = {
      ...palette,
      accent: mix(palette.text, palette.background, piece.foliageMix),
    };
    const kind = resolveKind(decoration.set, piece.kind, i);

    const start = startBase + i * stagger;
    const p = interpolate(frame, [start, start + enter], [0, 1], FLOW);
    const opacity = p * piece.opacity;
    const scale = 0.98 + 0.02 * p;
    const driftIn = -(1 - p) * DECOR_DRIFT_PX;

    // Gentle continuous life once in; eased on by the entrance progress so
    // pieces are calm while materializing, then ease into a soft, endless sway.
    // Phase is blended toward a shared base (SWAY_PHASE_SPREAD) so neighbors move
    // largely together — one soft breeze, not scattered bobbing.
    const swayPhase = piece.phase * SWAY_PHASE_SPREAD;
    const sway = Math.sin(t * SWAY_FREQ + swayPhase) * SWAY_DEG * p;
    const floatY = Math.sin(t * FLOAT_FREQ + swayPhase) * FLOAT_PX * p;

    return (
      <div
        key={i}
        style={{
          position: "absolute",
          left: `${piece.left}%`,
          top: `${piece.top}%`,
          opacity,
          filter: piece.blur ? `blur(${piece.blur}px)` : undefined,
          transform: `translate(-50%, -50%) translateY(${
            driftIn + floatY
          }px) rotate(${piece.rotate + sway}deg) scale(${scale})`,
          transformOrigin: "center",
        }}
      >
        <BloomPiece
          kind={kind}
          foliage={foliage}
          bloom={bloom}
          size={piece.size}
        />
      </div>
    );
  };

  // A single plane renders every piece — the faded BACK wash first, then the
  // crisp foreground over it (the back → front order the flattened `pieces` list
  // already carries), so the entrance stagger blooms the backdrop in first.
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {pieces.map((piece, i) => renderPiece(piece, i))}
    </div>
  );
}

// --- Lottie decoration (optional, additive) --------------------------------

// When the panel supplies one or more Lottie animations, they render alongside
// the SVG BloomDecor — but on their OWN, disjoint anchors (the ODD half of
// FRAME_ANCHORS), so a Lottie never lands on top of a botanical. The instance
// COUNT is driven by `lottieDensity`, independent of the SVG
// `decoration.density`; the chosen animations are distributed across the
// Lottie-allotted anchors by cycling. The center stays clear for the title.
// Each instance blooms in STAGGERED (from frame 0) and then sways gently
// forever, matching the SVG botanicals so both decoration layers move together.

// How many Lottie instances to place, by density — capped at the Lottie-allotted
// anchor count (7). Independent of the SVG botanicals' SVG_FRONT_COUNT.
const LOTTIE_COUNT: Record<LottieDensity, number> = {
  low: 3,
  med: 5,
  high: 7,
};

function LottieDecor({
  entries,
  density,
  recolorAmount,
  palette,
}: {
  entries: LottieRuntimeEntry[];
  density: LottieDensity;
  recolorAmount: number;
  palette: CardPalette;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // One independent clone PER anchor (blended toward the accent by
  // `recolorAmount` when THAT entry asks), so lottie-web's in-place annotation
  // can't bleed between instances. The chosen animations cycle across the Lottie
  // anchors. Recomputed only when the inputs change — never per frame.
  const instances = useMemo(() => {
    const count = LOTTIE_COUNT[density] ?? LOTTIE_COUNT.low;
    return LOTTIE_ANCHORS.slice(0, count).map((anchor, i) => {
      const entry = entries[i % entries.length];
      try {
        const data = entry.recolor
          ? recolorLottie(entry.data, palette.accent, recolorAmount)
          : cloneLottie(entry.data);
        return {
          anchor,
          data: data as Record<string, unknown> | null,
          loop: entry.loop,
        };
      } catch {
        return {
          anchor,
          data: null as Record<string, unknown> | null,
          loop: entry.loop,
        };
      }
    });
  }, [entries, density, recolorAmount, palette.accent]);

  // Per-instance entrance timing, shared with the SVG botanicals: staggered by
  // index from frame 0 so the Lotties establish WITH (not after) the garden.
  const enter = Math.round(DECOR_ENTER_SECONDS * fps);
  const stagger = 2; // frames between instances — visibly staggered, not all at once

  // Lotties are crisp foreground, matching the SVG botanicals' foreground so both
  // decoration layers move together.
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {instances.map(({ anchor, data, loop }, i) => {
        if (!data) return null;

        // Staggered materialize (fade + whisper of scale + small downward
        // settle) from frame 0, then a gentle, endless sway/float — the SAME
        // motion as the SVG botanicals, eased on by the entrance so instances are
        // calm while settling. Phase is blended toward a shared base
        // (SWAY_PHASE_SPREAD) so the Lotties drift WITH the botanicals as one
        // soft breeze, not on their own beat.
        const start = i * stagger;
        const p = interpolate(frame, [start, start + enter], [0, 1], FLOW);
        const scale = 0.98 + 0.02 * p;
        const driftIn = -(1 - p) * DECOR_DRIFT_PX;
        const swayPhase = anchor.phase * SWAY_PHASE_SPREAD;
        const sway = Math.sin(t * SWAY_FREQ + swayPhase) * SWAY_DEG * p;
        const floatY = Math.sin(t * FLOAT_FREQ + swayPhase) * FLOAT_PX * p;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${anchor.left}%`,
              top: `${anchor.top}%`,
              opacity: anchor.opacity * p,
              transform: `translate(-50%, -50%) translateY(${
                driftIn + floatY
              }px) rotate(${sway}deg) scale(${scale})`,
              transformOrigin: "center",
            }}
          >
            <Lottie
              // Lottie JSON is a superset of LottieAnimationData; typed loosely
              // (see LottiePreview) so callers needn't assert the exact shape.
              animationData={data as unknown as LottieAnimationData}
              // loop off = play once and HOLD the final frame: @remotion/lottie
              // clamps the driven frame to min(frame, totalFrames - 1), so a
              // one-shot "grow" animation settles fully grown instead of snapping
              // back to nothing every cycle.
              loop={loop}
              style={{
                width: anchor.size * LOTTIE_BOX_SCALE,
                height: anchor.size * LOTTIE_BOX_SCALE,
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

// --- card ------------------------------------------------------------------

// The title + subtitle, rendered INSIDE a delayed <Sequence> (see GardenBloom)
// so the shared soft entrance (`useTextEntrance`, default "rise") begins only
// AFTER the garden has started to bloom in — the title rises into the
// establishing composition, the subtitle fading in just after it.
function GardenTitle({ props }: { props: CardProps }) {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const { style, text } = useTextEntrance(props.animation, props.title);
  const subOpacity = useFadeIn(0.6, 0.7);

  const muted = mix(palette.text, palette.background, 0.3);

  const words = props.title.split(/\s+/).filter(Boolean);
  const highlightWords = new Set(
    (props.highlight ?? "").split(/\s+/).map(normWord).filter(Boolean),
  );

  return (
    // Centered block (see GardenBloom's plate): the title sits centered in the
    // frame. `maxWidth` wraps the headline to a couple of comfortable centered
    // lines instead of one wide banner.
    <div
      style={{
        maxWidth: 1040,
        textAlign: "center",
      }}
    >
      <h1
        style={{
          margin: 0,
          fontFamily: font,
          fontWeight: 800,
          fontSize: 116,
          lineHeight: 1.06,
          letterSpacing: "-0.015em",
          color: palette.text,
          ...style,
        }}
      >
        {highlightWords.size === 0
          ? text
          : words.map((word, i) => {
              const hi = highlightWords.has(normWord(word));
              return (
                <span
                  key={i}
                  style={{ color: hi ? palette.accent : undefined }}
                >
                  {i > 0 ? " " : ""}
                  {word}
                </span>
              );
            })}
      </h1>

      {props.subtitle ? (
        <p
          style={{
            margin: "34px 0 0",
            fontFamily: font,
            fontWeight: 400,
            fontSize: 44,
            lineHeight: 1.25,
            color: muted,
            opacity: subOpacity,
          }}
        >
          {props.subtitle}
        </p>
      ) : null}
    </div>
  );
}

export const GardenBloom = (props: CardProps) => {
  const { palette } = props;
  const { fps } = useVideoConfig();

  // Entrance = the scene EMERGING from black; exit = a soft fade-OUT. Both run
  // off the GLOBAL frame here (outside the title's <Sequence>), so the whole
  // scene shares one clock. `emerge` fades the gradient + atmosphere up from
  // black; the decorations + title carry their OWN entrances on top of it.
  const emerge = useEmerge();
  const fadeOut = useFadeOut();

  // Lottie decorations layer OVER the SVG botanicals (both render). Keep only
  // the non-null, well-formed entries so a not-yet-loaded or malformed file
  // can't crash the card; if none survive, the botanicals simply show alone.
  const lottieEntries = useMemo(
    () =>
      (props.lottieData ?? []).filter(
        (e): e is LottieRuntimeEntry => !!e && isLikelyLottie(e.data),
      ),
    [props.lottieData],
  );

  // Decorations bloom in from frame 0; the title arrives AFTER the garden has
  // established (~0.95s in, as the bloom is finishing settling). A <Sequence>
  // offset shifts the title's entrance clock to start here (its `useTextEntrance`
  // runs from local frame 0 once the sequence mounts), so the garden blooms in,
  // then the title rises into it.
  const titleDelay = Math.round(0.95 * fps);

  // The STAGE is the BLACK BACKDROP the whole scene blooms up from (and departs
  // back to via `fadeOut`). There is no zoom or pan anywhere; `overflow: hidden`
  // just clips the edge-bleeding botanicals to the frame. The gradient wash sits
  // in its OWN layer so it can emerge up from black WITHOUT dimming the
  // decorations, which bloom on their own.
  return (
    <AbsoluteFill
      style={{
        opacity: fadeOut,
        backgroundColor: "#000",
        overflow: "hidden",
      }}
    >
      {/* The garden gradient wash, emerging up from the black stage over the
          entrance — timed (useEmerge) to overlap the bloom so there is no seam
          between "from black" and the decorations blooming in. */}
      <AbsoluteFill style={{ opacity: emerge }}>
        <Background palette={palette} background={props.background} />
      </AbsoluteFill>

      {/* Dappled sun — far, behind the botanicals; fades up WITH the gradient so
          it never glows on pure black at frame 0. */}
      <AtmosphereLight enter={emerge} />
      <BloomDecor palette={palette} decoration={props.decoration} />
      {lottieEntries.length > 0 ? (
        <LottieDecor
          entries={lottieEntries}
          density={props.lottieDensity ?? "low"}
          recolorAmount={props.lottieRecolorAmount ?? 0.8}
          palette={palette}
        />
      ) : null}
      {/* Floating motes — in front of the garden but behind the title; emerge
          with the scene too. Self-positions absolute inset:0, no wrapper. */}
      <AtmosphereMotes enter={emerge} />

      {/* Centered title plane: horizontally + vertically centered, held STATIC
          (no zoom/pan) so the crisp title stays pixel-stable — only its one-time
          entrance rise moves it, arriving ~0.95s in as the garden finishes
          establishing. */}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <Sequence from={titleDelay} layout="none">
          <GardenTitle props={props} />
        </Sequence>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
