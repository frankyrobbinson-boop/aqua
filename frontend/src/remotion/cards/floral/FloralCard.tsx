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
 * Two archetypes: "center" frames a centered hero title with the botanicals as a
 * border; "left" anchors the title (and optional body) on the left with the
 * botanicals massed on the right. Its own cream canvas, independent of the app
 * theme. Siblings imported by RELATIVE path (no `@/*` alias in the Remotion
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
  const { style: titleStyle, text: titleText } = useTextEntrance(
    props.animation,
    props.title,
  );
  const bodyOpacity = useFadeIn(0.5, 0.7);
  const bodyColor = props.bodyColor || DEFAULT_BODY_COLOR;
  const isCenter = variant.layout === "center";

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
          alignItems: isCenter ? "center" : "flex-start",
          textAlign: isCenter ? "center" : "left",
          padding: isCenter ? "0 320px" : "0 0 0 120px",
        }}
      >
        <div style={{ maxWidth: isCenter ? undefined : 780 }}>
          <h1
            style={{
              margin: 0,
              fontFamily: font,
              fontWeight: 400,
              fontSize: isCenter ? 180 : 108,
              lineHeight: isCenter ? 1.0 : 1.06,
              letterSpacing: "-0.01em",
              color: palette.text,
              ...titleStyle,
            }}
          >
            {titleText}
          </h1>

          {props.subtitle ? (
            <p
              style={{
                margin: isCenter ? "34px 0 0" : "30px 0 0",
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
