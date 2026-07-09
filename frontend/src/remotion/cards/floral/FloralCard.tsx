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

  // Single-line hero size (title/hook cards): cap by length and let the browser
  // BALANCE the wrap so a long promise splits into even lines. Title (center)
  // cards keep the big hero size.
  const contentFontSize =
    props.title.trim().length > 26 ? 74 : props.title.trim().length > 16 ? 88 : 104;
  // Two-tier subject size (the item name) — its own length cap so a long name
  // wraps in the column; the label sits a tier LARGER above it. Both tiers are
  // sized up hard (label 160, subject 88/108/128) so the header reads big.
  const subjectLen = props.title.trim().length;
  const subjectFontSize = subjectLen > 26 ? 88 : subjectLen > 16 ? 108 : 128;
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
                  ? 180
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
