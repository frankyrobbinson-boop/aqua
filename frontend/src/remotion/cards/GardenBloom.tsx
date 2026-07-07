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
 *   - Every piece FLOATS in with a staggered, graceful settle — a soft downward
 *     drift + fade with only a whisper of scale — back layer first, each easing
 *     ~1.4s on a slow-in/slow-out cubic (Easing.inOut) so nothing pops; once in,
 *     it sways gently forever (Math.sin), the sway easing on with the entrance so
 *     the settle blends seamlessly into the drift.
 *   - Foliage greens derive from `palette.text`, softer the further back a layer
 *     sits; blooms/berries + the optional `highlight` word use `palette.accent`
 *     (a warm floral rose by default). Fully recolorable via `palette`.
 *
 * The title uses the shared soft entrance (`useTextEntrance`, default "rise");
 * the subtitle fades in after. Everything is deterministic (frame-based only;
 * NO Math.random / Date.now) and siblings are imported by RELATIVE path (no
 * `@/*` alias in the Remotion bundle), so the <Player> preview matches the MP4
 * render frame-for-frame.
 */
import { useMemo } from "react";
import { Lottie, type LottieAnimationData } from "@remotion/lottie";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { useFadeIn, useTextEntrance } from "../animations";
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

// Frame-interpolate preset: a slow-in/slow-out cubic so decorations glide — not
// pop — into place, clamped both ends so values hold once the entrance ends.
const FLOW = {
  easing: Easing.inOut(Easing.cubic),
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

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
// reads balanced. Positions hug the edges/corners (center kept clear for the
// title), and every SVG anchor sits well clear of every Lottie anchor, so
// nothing piles up even at max density.
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
  // pair 0 — SVG top-left corner / Lottie bottom-center
  { left: 8, top: 12, size: 190, rotate: -16, phase: 0.0, kind: "broadleaf", opacity: 0.82 },
  { left: 50, top: 95, size: 165, rotate: 0, phase: 0.4, kind: "flower", opacity: 0.92 },
  // pair 1 — SVG top-right corner / Lottie top-left
  { left: 92, top: 12, size: 185, rotate: 18, phase: 1.1, kind: "broadleaf", opacity: 0.82 },
  { left: 28, top: 7, size: 170, rotate: 0, phase: 1.3, kind: "leaf", opacity: 0.62 },
  // pair 2 — SVG bottom-right / Lottie top-right
  { left: 72, top: 94, size: 165, rotate: 20, phase: 2.0, kind: "berry", opacity: 0.94 },
  { left: 72, top: 7, size: 170, rotate: 0, phase: 2.2, kind: "flower", opacity: 0.62 },
  // pair 3 — SVG bottom-left / Lottie bottom-left corner
  { left: 28, top: 94, size: 165, rotate: -18, phase: 0.7, kind: "berry", opacity: 0.94 },
  { left: 8, top: 88, size: 180, rotate: 0, phase: 0.9, kind: "leaf", opacity: 0.75 },
  // pair 4 — SVG left-lower / Lottie bottom-right corner
  { left: 6, top: 66, size: 150, rotate: -24, phase: 1.7, kind: "sprig", opacity: 0.9 },
  { left: 92, top: 88, size: 180, rotate: 0, phase: 1.9, kind: "flower", opacity: 0.75 },
  // pair 5 — SVG right-lower / Lottie left-upper
  { left: 94, top: 66, size: 150, rotate: 22, phase: 2.6, kind: "sprig", opacity: 0.9 },
  { left: 6, top: 34, size: 150, rotate: 0, phase: 2.8, kind: "leaf", opacity: 0.6 },
  // pair 6 — SVG top-center / Lottie right-upper
  { left: 50, top: 5.5, size: 130, rotate: 4, phase: 3.1, kind: "flower", opacity: 0.96 },
  { left: 94, top: 34, size: 150, rotate: 0, phase: 0.5, kind: "flower", opacity: 0.6 },
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

  // Entrance: each piece FLOATS in — a gentle downward settle + fade, with only
  // a whisper of scale — staggered by index so the garden drifts in gracefully.
  const startBase = Math.round(0.06 * fps);
  const stagger = 2; // frames between pieces
  const enter = Math.round(1.4 * fps); // slow, flowing entrance per piece

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {pieces.map((piece, i) => {
        const foliage: CardPalette = {
          ...palette,
          accent: mix(palette.text, palette.background, piece.foliageMix),
        };
        const kind = resolveKind(decoration.set, piece.kind, i);

        const start = startBase + i * stagger;
        const p = interpolate(frame, [start, start + enter], [0, 1], FLOW);
        const opacity = p * piece.opacity;
        const scale = 0.9 + 0.1 * p;
        const driftIn = -(1 - p) * 40;

        // Gentle continuous life once in; eased on by the entrance progress so
        // pieces are calm while settling, then ease into a soft, endless sway.
        const sway = Math.sin(t * 0.85 + piece.phase) * 4 * p;
        const floatY = Math.sin(t * 0.75 + piece.phase) * 7 * p;

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
      })}
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
  recolor,
  palette,
}: {
  entries: LottieRuntimeEntry[];
  density: LottieDensity;
  recolor: boolean;
  palette: CardPalette;
}) {
  // One independent clone PER anchor (recolored to the accent when asked), so
  // lottie-web's in-place annotation can't bleed between instances. The chosen
  // animations cycle across the Lottie anchors. Recomputed only when the inputs
  // change — never per frame.
  const instances = useMemo(() => {
    const count = LOTTIE_COUNT[density] ?? LOTTIE_COUNT.low;
    return LOTTIE_ANCHORS.slice(0, count).map((anchor, i) => {
      const entry = entries[i % entries.length];
      try {
        const data = recolor
          ? recolorLottie(entry.data, palette.accent)
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
  }, [entries, density, recolor, palette.accent]);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {instances.map(({ anchor, data, loop }, i) =>
        data ? (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${anchor.left}%`,
              top: `${anchor.top}%`,
              opacity: anchor.opacity,
              transform: "translate(-50%, -50%)",
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
        ) : null,
      )}
    </div>
  );
}

// --- card ------------------------------------------------------------------

export const GardenBloom = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const { style, text } = useTextEntrance(props.animation, props.title);
  const subOpacity = useFadeIn(0.6, 0.7);

  const muted = mix(palette.text, palette.background, 0.3);

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

  const words = props.title.split(/\s+/).filter(Boolean);
  const highlightWords = new Set(
    (props.highlight ?? "").split(/\s+/).map(normWord).filter(Boolean),
  );

  return (
    <Background
      palette={palette}
      background={props.background}
      decoration={
        <>
          <BloomDecor palette={palette} decoration={props.decoration} />
          {lottieEntries.length > 0 ? (
            <LottieDecor
              entries={lottieEntries}
              density={props.lottieDensity ?? "low"}
              recolor={props.lottieRecolor ?? true}
              palette={palette}
            />
          ) : null}
        </>
      }
    >
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          padding: "0 240px",
          textAlign: "center",
        }}
      >
        {/* Nudged slightly high to leave room for the botanicals below. */}
        <div style={{ transform: "translateY(-24px)" }}>
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
      </AbsoluteFill>
    </Background>
  );
};
