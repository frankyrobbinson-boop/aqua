/**
 * FloralCard — the single parameterized component behind every "floral" card
 * style slide. It reads `props.variant` to pick a layout archetype + botanical
 * layer set (see variants.ts), then renders:
 *   - the shared paper texture as a full-bleed background <Img>,
 *   - each botanical cluster as its OWN <Img> layer with an independent,
 *     staggered eased entrance (useLayerEntrance) plus a slow idle sway,
 *   - the title (Questrial, plum, trailing period typed into the text) via the
 *     shared useTextEntrance, and
 *   - the body (the `subtitle`, taupe) via useFadeIn when present.
 *
 * Three archetypes: "center" frames a centered hero title with the botanicals as
 * a border; "left"/"right" anchor the title (and optional body) on that side with
 * the botanicals massed on the OTHER. Its own cream canvas, independent of the
 * app theme. Siblings imported by RELATIVE path (no `@/*` alias in the Remotion
 * bundle).
 */
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { useFadeIn, useLayerEntrance, useTextEntrance } from "../../animations";
import { resolveFontFamily } from "../theme";
import type { CardProps } from "../types";
import {
  type FloralLayer,
  resolveFloralVariant,
} from "./variants";

// Shared background texture (public/cardstyle/texture.jpg), identical across
// every floral slide.
const TEXTURE_SRC = "cardstyle/texture.jpg";
const BOTANICALS_DIR = "cardstyle/botanicals/";
// Soft taupe body default when `bodyColor` isn't supplied.
const DEFAULT_BODY_COLOR = "#7f7268";
// Two-tier SUBJECT tier color — a plum a shade DARKER than the label (which
// takes the card's `palette.text` plum), so the item name reads as a quieter
// second tier beneath the big label. A constant (not palette-derived) so the
// darker-than-label relationship holds regardless of the preset palette.
const SUBJECT_COLOR = "#6f3557";
// Idle sway speed (rad/s of composition time), matching the garden vines' calm.
const SWAY_SPEED = 0.8;

/** One botanical cluster: its own staggered entrance + slow idle sway. A child
 *  component so the entrance hook is called once per instance (not in a loop). */
function BotanicalLayer({ layer }: { layer: FloralLayer }) {
  const { opacity, transform } = useLayerEntrance(layer.delay, {
    dir: layer.dir,
    driftPx: layer.driftPx,
  });
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const swayDeg =
    (layer.sway ?? 0) * Math.sin((frame / fps) * SWAY_SPEED + (layer.phase ?? 0));

  return (
    <Img
      src={staticFile(BOTANICALS_DIR + layer.src)}
      style={{
        position: "absolute",
        left: `${layer.x * 100}%`,
        top: `${layer.y * 100}%`,
        width: `${layer.w * 100}%`,
        height: `${layer.h * 100}%`,
        transformOrigin: "center",
        opacity,
        transform: `${transform} rotate(${swayDeg}deg)`,
      }}
    />
  );
}

// --- Auto-fit sizing -------------------------------------------------------
// The card text must never spill outside the card: a long title (or a long
// section subject) shrinks until it fits the available box. We size
// ANALYTICALLY rather than measuring the DOM — the headless Remotion render has
// no reliable post-font-load measure pass (and @remotion/layout-utils isn't a
// dependency), so an estimate keyed off the font's average glyph advance is the
// deterministic, font-load-independent choice. GLYPH_ADVANCE is calibrated to
// Questrial (~0.55em average advance, verified against a rendered title);
// SPACE_ADVANCE is a space's narrower advance; LINE_BOX_OVERHEAD pads each block
// for the ascenders/descenders that sit outside the nominal line box at these
// tight line-heights. The estimate is deliberately a touch conservative, so it
// errs toward shrinking (never toward overflow).
const GLYPH_ADVANCE = 0.55;
const SPACE_ADVANCE = 0.28;
const LINE_BOX_OVERHEAD = 0.12;

/** Estimate how many lines `text` wraps into at `fontSize` within `maxWidth`,
 *  greedily fitting whole words (matching how the browser wraps; `textWrap:
 *  balance` only evens the lines, it doesn't change the count). */
function estimateLineCount(
  text: string,
  fontSize: number,
  maxWidth: number,
): number {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return 1;
  const space = fontSize * SPACE_ADVANCE;
  let lines = 1;
  let lineWidth = 0;
  for (const word of words) {
    const wordWidth = word.length * fontSize * GLYPH_ADVANCE;
    if (lineWidth === 0) {
      lineWidth = wordWidth;
    } else if (lineWidth + space + wordWidth <= maxWidth) {
      lineWidth += space + wordWidth;
    } else {
      lines += 1;
      lineWidth = wordWidth;
    }
  }
  return lines;
}

/** Largest integer font size in `[minFontSize, maxFontSize]` at which `text`
 *  fits within `maxWidth` × `maxHeight` (given `lineHeight`), estimated
 *  analytically. Short text stays at `maxFontSize`; long text shrinks to stay in
 *  bounds (wrapping across a few lines). Also guards the widest single word so a
 *  long word never overruns the width. Falls back to `minFontSize`. */
function fitFontSize(
  text: string,
  {
    maxFontSize,
    minFontSize,
    maxWidth,
    maxHeight,
    lineHeight,
  }: {
    maxFontSize: number;
    minFontSize: number;
    maxWidth: number;
    maxHeight: number;
    lineHeight: number;
  },
): number {
  const words = text.split(/\s+/).filter(Boolean);
  const longestWord = words.reduce((m, w) => Math.max(m, w.length), 0);
  for (let size = maxFontSize; size > minFontSize; size -= 2) {
    const lines = estimateLineCount(text, size, maxWidth);
    const height = lines * size * (lineHeight + LINE_BOX_OVERHEAD);
    const widestWord = longestWord * size * GLYPH_ADVANCE;
    if (height <= maxHeight && widestWord <= maxWidth) return size;
  }
  return minFontSize;
}

export const FloralCard = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const variant = resolveFloralVariant(props.variant);
  const bodyColor = props.bodyColor || DEFAULT_BODY_COLOR;
  const isCenter = variant.layout === "center";
  const isRight = variant.layout === "right";

  // Two-tier section header: when an `index` is present the card announces the
  // item in two stacked tiers — a big animated LABEL ("{itemNoun} #{index}",
  // e.g. "Flower #1", no trailing period) over a SUBJECT a size down and a plum
  // shade darker (the item name in `title`). A title/hook card (no index) stays
  // a single hero line, unchanged: `label` is then just the title, so the SAME
  // useTextEntrance animates it.
  const idx = props.index?.trim();
  const noun = props.itemNoun?.trim();
  const isTwoTier = Boolean(idx);
  const label = isTwoTier
    ? `${noun ? `${noun} ` : ""}#${idx}`
    : props.title;
  const { style: titleStyle, text: titleText } = useTextEntrance(
    props.animation,
    label,
  );
  // Subject fades in a touch after the label lands; body later still.
  const subjectOpacity = useFadeIn(0.3, 0.6);
  const bodyOpacity = useFadeIn(0.5, 0.7);

  // Single-line hero size (left/right title/hook cards): cap by length and let
  // the browser BALANCE the wrap so a long promise splits into even lines.
  const contentFontSize =
    props.title.trim().length > 26 ? 74 : props.title.trim().length > 16 ? 88 : 104;
  // Centered hero title (the title card): start at the big hero size and AUTO-FIT
  // DOWN so a long title wraps within the card instead of running off the bottom.
  // The center layout pads 320px each side (≈1240px usable width); the title owns
  // the full height when there's no body, less when a subtitle is present.
  const centerTitleFontSize = fitFontSize(props.title, {
    maxFontSize: 180,
    minFontSize: 56,
    maxWidth: 1240,
    maxHeight: props.subtitle ? 540 : 880,
    lineHeight: 1.0,
  });
  // Two-tier subject size (the item name): the length cap is the STARTING size
  // (the label sits a tier LARGER above it), then AUTO-FIT down so an unusually
  // long name still fits its column instead of overflowing. Existing names fit at
  // their tier, so this leaves them unchanged.
  const subjectLen = props.title.trim().length;
  const subjectMaxFontSize = subjectLen > 26 ? 88 : subjectLen > 16 ? 108 : 128;
  const subjectFontSize = fitFontSize(props.title, {
    maxFontSize: subjectMaxFontSize,
    minFontSize: 48,
    maxWidth: 760,
    maxHeight: 520,
    lineHeight: 1.05,
  });
  const LABEL_FONT_SIZE = 160;

  return (
    <AbsoluteFill style={{ backgroundColor: palette.background }}>
      <Img
        src={staticFile(TEXTURE_SRC)}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />

      {variant.layers.map((layer) => (
        <BotanicalLayer key={layer.src} layer={layer} />
      ))}

      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: isCenter ? "center" : isRight ? "flex-end" : "flex-start",
          textAlign: isCenter ? "center" : isRight ? "right" : "left",
          padding: isCenter ? "0 320px" : isRight ? "0 120px 0 0" : "0 0 0 120px",
        }}
      >
        <div style={{ maxWidth: isCenter ? undefined : 820 }}>
          <h1
            style={{
              margin: 0,
              fontFamily: font,
              fontWeight: 400,
              fontSize: isTwoTier
                ? LABEL_FONT_SIZE
                : isCenter
                  ? centerTitleFontSize
                  : contentFontSize,
              lineHeight: isTwoTier ? 1.02 : isCenter ? 1.0 : 1.05,
              letterSpacing: "-0.01em",
              textWrap: "balance",
              color: palette.text,
              ...titleStyle,
            }}
          >
            {titleText}
          </h1>

          {isTwoTier ? (
            <div
              style={{
                margin: isRight ? "18px 0 0 auto" : "18px 0 0",
                maxWidth: isCenter ? undefined : 760,
                fontFamily: font,
                fontWeight: 400,
                fontSize: subjectFontSize,
                lineHeight: 1.05,
                letterSpacing: "-0.01em",
                textWrap: "balance",
                color: SUBJECT_COLOR,
                opacity: subjectOpacity,
              }}
            >
              {props.title}
            </div>
          ) : null}

          {props.subtitle ? (
            <p
              style={{
                margin: isCenter ? "34px 0 0" : isRight ? "30px 0 0 auto" : "30px 0 0",
                maxWidth: isCenter ? undefined : 720,
                fontFamily: font,
                fontWeight: 400,
                fontSize: isCenter ? 44 : 38,
                lineHeight: 1.4,
                color: bodyColor,
                opacity: bodyOpacity,
              }}
            >
              {props.subtitle}
            </p>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
