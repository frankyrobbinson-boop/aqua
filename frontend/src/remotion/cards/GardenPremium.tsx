/**
 * GardenPremium — a refined, "premium" garden title card that stacks the
 * high-impact moves the cleaner cards omit:
 *   - an uppercase, wide-tracked kicker with an accent rule + dot,
 *   - a per-word MASKED title reveal (each word rises into place behind its own
 *     overflow-hidden mask, one at a time) with optional keyword emphasis,
 *   - a soft translucent panel with generous padding + a faint drop-shadow,
 *   - very subtle film grain (fixed-seed feTurbulence) + a soft radial vignette,
 *   - layered botanicals: one LARGE faded corner vine behind the panel plus
 *     crisp small accents in the corners.
 *
 * Muted warm-neutral palette by default (see CARD_DEFAULT_OVERRIDES in
 * defaults.ts); still fully recolorable via `palette`. The title motion is
 * intentionally self-contained and does NOT use the shared `animation` prop —
 * the masked word-rise is this card's signature.
 *
 * Everything is deterministic (frame-based only; NO Math.random / Date.now) and
 * siblings are imported by RELATIVE path (no `@/*` alias in the Remotion
 * bundle), so the <Player> preview matches the MP4 render frame-for-frame.
 */
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { Background } from "./Background";
import { Flower, Leaf, Sprig, VineCorner } from "./decorations";
import { darken, lighten, mix, resolveFontFamily } from "./theme";
import type {
  CardDecoration,
  CardPalette,
  CardProps,
  DecorationSet,
} from "./types";

// --- helpers ---------------------------------------------------------------

/** #rrggbb → `rgba()` so the panel / vignette can sit translucently over the
 *  fill. Falls back to white on a malformed hex (the Player can render a color
 *  the user is mid-typing). Local to this card so theme.ts stays untouched. */
function hexToRgba(hex: string, alpha: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return `rgba(255, 255, 255, ${alpha})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Frame-interpolate presets: clamp both ends so values hold once the intro ends.
const CUBIC_OUT = {
  easing: Easing.out(Easing.cubic),
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};
const EASE_OUT = {
  easing: Easing.out(Easing.ease),
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

/** Lowercase + strip leading/trailing punctuation, so a `highlight` of "Bloom"
 *  matches a title word "Bloom," or "Bloom". */
const normWord = (w: string): string =>
  w.toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");

// --- layered decoration ----------------------------------------------------

// How many crisp corner accents each density shows (the large faded vine is
// separate). Density scales the accents; `set` picks their shape.
const CORNER_COUNT: Record<CardDecoration["density"], number> = {
  none: 0,
  low: 1,
  med: 2,
  high: 2,
};

function smallShape(
  set: DecorationSet,
  i: number,
  palette: CardPalette,
  size: number,
) {
  const kind =
    set === "flowers"
      ? "flower"
      : set === "mixed"
        ? (["sprig", "leaf", "flower"] as const)[i % 3]
        : i % 2 === 0
          ? "sprig"
          : "leaf";
  if (kind === "flower") return <Flower palette={palette} size={size} />;
  if (kind === "leaf") return <Leaf palette={palette} size={size} />;
  return <Sprig palette={palette} size={size} />;
}

function PremiumDecor({
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

  const corners = CORNER_COUNT[decoration.density] ?? CORNER_COUNT.low;
  const swayA = Math.sin(t * 0.8) * 3;
  const swayB = Math.sin(t * 0.8 + 1.4) * 3;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {/* Large, very faded corner vine bleeding off the top-right, behind the
          panel — the layered depth cue. */}
      <div
        style={{
          position: "absolute",
          top: -200,
          right: -200,
          opacity: 0.1,
          transform: `scaleX(-1) rotate(${swayA}deg)`,
          transformOrigin: "center",
        }}
      >
        <VineCorner palette={palette} size={860} />
      </div>

      {/* Crisp small accents tucked into the left corners. */}
      {corners >= 1 ? (
        <div
          style={{
            position: "absolute",
            left: 96,
            bottom: 92,
            transform: `rotate(${-14 + swayB}deg)`,
            transformOrigin: "center",
          }}
        >
          {smallShape(decoration.set, 0, palette, 150)}
        </div>
      ) : null}
      {corners >= 2 ? (
        <div
          style={{
            position: "absolute",
            left: 128,
            top: 150,
            transform: `rotate(${18 + swayA}deg)`,
            transformOrigin: "center",
          }}
        >
          {smallShape(decoration.set, 1, palette, 112)}
        </div>
      ) : null}
    </div>
  );
}

// --- card ------------------------------------------------------------------

export const GardenPremium = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const words = props.title.split(/\s+/).filter(Boolean);
  const wordCount = Math.max(words.length, 1);

  const highlightWords = new Set(
    (props.highlight ?? "")
      .split(/\s+/)
      .map(normWord)
      .filter(Boolean),
  );

  // Timing (frames). The title reveals word-by-word; the subtitle waits for it
  // to finish before rising in.
  const titleStart = Math.round(0.12 * fps);
  const wordStagger = 5;
  const wordReveal = Math.round(0.5 * fps);
  const titleEnd = titleStart + (wordCount - 1) * wordStagger + wordReveal;

  const eyebrowEnd = Math.round(0.45 * fps);
  const eyebrowOpacity = interpolate(frame, [0, eyebrowEnd], [0, 1], EASE_OUT);
  const eyebrowY = interpolate(frame, [0, eyebrowEnd], [16, 0], CUBIC_OUT);

  const subStart = titleEnd + Math.round(0.1 * fps);
  const subEnd = subStart + Math.round(0.5 * fps);
  const subOpacity = interpolate(frame, [subStart, subEnd], [0, 1], EASE_OUT);
  const subY = interpolate(frame, [subStart, subEnd], [24, 0], CUBIC_OUT);

  const muted = mix(palette.text, palette.background, 0.3);
  const kicker = mix(palette.text, palette.background, 0.18);

  const panelBg = hexToRgba(lighten(palette.background, 0.5), 0.55);
  const panelBorder = hexToRgba(lighten(palette.background, 0.75), 0.6);

  return (
    <Background
      palette={palette}
      background={props.background}
      decoration={
        <PremiumDecor palette={palette} decoration={props.decoration} />
      }
    >
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          padding: "0 160px",
        }}
      >
        <div
          style={{
            position: "relative",
            maxWidth: 1360,
            padding: "76px 104px 84px",
            borderRadius: 44,
            background: panelBg,
            border: `1px solid ${panelBorder}`,
            boxShadow: "0 44px 130px -50px rgba(0, 0, 0, 0.45)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
          }}
        >
          {/* Eyebrow / kicker — accent rule + label + dot. */}
          {props.eyebrow ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 18,
                marginBottom: 34,
                opacity: eyebrowOpacity,
                transform: `translateY(${eyebrowY}px)`,
              }}
            >
              <span
                style={{
                  width: 44,
                  height: 3,
                  borderRadius: 999,
                  background: palette.accent,
                }}
              />
              <span
                style={{
                  fontFamily: font,
                  fontWeight: 700,
                  fontSize: 28,
                  letterSpacing: "0.34em",
                  textTransform: "uppercase",
                  color: kicker,
                }}
              >
                {props.eyebrow}
              </span>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 999,
                  background: palette.accent,
                }}
              />
            </div>
          ) : null}

          {/* Title — per-word masked rise; highlighted words in the accent. */}
          <h1
            style={{
              margin: 0,
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              columnGap: "0.3em",
              rowGap: "0.08em",
              fontFamily: font,
              fontWeight: 700,
              fontSize: 112,
              lineHeight: 1.08,
              letterSpacing: "-0.015em",
              color: palette.text,
            }}
          >
            {words.map((word, i) => {
              const start = titleStart + i * wordStagger;
              const y = interpolate(
                frame,
                [start, start + wordReveal],
                [120, 0],
                CUBIC_OUT,
              );
              const isHi = highlightWords.has(normWord(word));
              return (
                <span
                  key={i}
                  style={{
                    display: "inline-block",
                    overflow: "hidden",
                    verticalAlign: "top",
                    paddingBottom: "0.1em",
                    marginBottom: "-0.1em",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      transform: `translateY(${y}%)`,
                      color: isHi ? palette.accent : undefined,
                    }}
                  >
                    {word}
                  </span>
                </span>
              );
            })}
          </h1>

          {/* Subtitle — rises/fades in after the title finishes. */}
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
                transform: `translateY(${subY}px)`,
              }}
            >
              {props.subtitle}
            </p>
          ) : null}
        </div>
      </AbsoluteFill>

      {/* Soft radial vignette — subtle, over the content. */}
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background: `radial-gradient(125% 125% at 50% 42%, transparent 55%, ${hexToRgba(
            darken(palette.background, 0.55),
            0.4,
          )} 100%)`,
        }}
      />

      {/* Very subtle film grain — FIXED seed => deterministic (no randomness). */}
      <svg
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          opacity: 0.05,
          mixBlendMode: "overlay",
        }}
      >
        <filter id="garden-premium-grain">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves={2}
            seed={7}
            stitchTiles="stitch"
          />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#garden-premium-grain)" />
      </svg>
    </Background>
  );
};
