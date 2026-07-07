/**
 * GardenFramed — a centered title inside a soft inset border, with botanical
 * vines curling out of each corner. The corner vines share the same palette and
 * a gentle, out-of-sync sway. When decorations are off, only the inset border
 * remains. Its own light canvas.
 *
 * Siblings are imported by RELATIVE path (no `@/*` alias in the Remotion bundle).
 */
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { useFadeIn, useTextEntrance } from "../animations";
import { Background } from "./Background";
import { VineCorner } from "./decorations";
import { mix, resolveFontFamily } from "./theme";
import type { CardDecoration, CardPalette, CardProps } from "./types";

const VINE_SIZE = 300;
const SWAY_SPEED = 0.9;
const SWAY_DEG = 3;

const CORNERS = [
  { key: "tl", pos: { top: 40, left: 40 }, flip: "scale(1, 1)", phase: 0.0 },
  { key: "tr", pos: { top: 40, right: 40 }, flip: "scale(-1, 1)", phase: 1.2 },
  { key: "bl", pos: { bottom: 40, left: 40 }, flip: "scale(1, -1)", phase: 2.1 },
  { key: "br", pos: { bottom: 40, right: 40 }, flip: "scale(-1, -1)", phase: 0.6 },
] as const;

function VineFrame({
  palette,
  decoration,
}: {
  palette: CardPalette;
  decoration: CardDecoration;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const borderColor = mix(palette.accent, palette.background, 0.3);
  const showVines =
    decoration.set !== "none" && decoration.density !== "none";

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          inset: 70,
          border: `3px solid ${borderColor}`,
          borderRadius: 28,
        }}
      />
      {showVines
        ? CORNERS.map((c) => {
            const sway = Math.sin(t * SWAY_SPEED + c.phase) * SWAY_DEG;
            return (
              <div
                key={c.key}
                style={{
                  position: "absolute",
                  ...c.pos,
                  width: VINE_SIZE,
                  height: VINE_SIZE,
                  transform: `${c.flip} rotate(${sway}deg)`,
                  transformOrigin: "center",
                }}
              >
                <VineCorner palette={palette} size={VINE_SIZE} />
              </div>
            );
          })
        : null}
    </div>
  );
}

export const GardenFramed = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const { style, text } = useTextEntrance(props.animation, props.title);
  const subOpacity = useFadeIn(0.5, 0.7);
  // Section-header number badge: a soft accent pill above the title, with its
  // own gentle fade+rise that slightly leads the title. Renders nothing when
  // `index` is empty, so a card with no index is unchanged.
  const badgeOpacity = useFadeIn(0, 0.5);

  const muted = mix(palette.text, palette.background, 0.28);
  const idx = props.index?.trim();
  const badgeBg = mix(palette.accent, palette.background, 0.2);
  const badgeText = mix(palette.accent, palette.text, 0.55);

  return (
    <Background
      palette={palette}
      background={props.background}
      decoration={<VineFrame palette={palette} decoration={props.decoration} />}
    >
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          padding: "0 240px",
          textAlign: "center",
        }}
      >
        {idx ? (
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 28,
              padding: "10px 30px",
              borderRadius: 999,
              background: badgeBg,
              color: badgeText,
              fontFamily: font,
              fontWeight: 700,
              fontSize: 36,
              lineHeight: 1,
              letterSpacing: "0.04em",
              opacity: badgeOpacity,
              transform: `translateY(${(1 - badgeOpacity) * 10}px)`,
            }}
          >
            {idx}
          </div>
        ) : null}

        <h1
          style={{
            margin: 0,
            fontFamily: font,
            fontWeight: 700,
            fontSize: 104,
            lineHeight: 1.08,
            letterSpacing: "-0.01em",
            color: palette.text,
            ...style,
          }}
        >
          {text}
        </h1>

        {props.subtitle ? (
          <p
            style={{
              margin: "30px 0 0",
              fontFamily: font,
              fontWeight: 400,
              fontSize: 42,
              lineHeight: 1.2,
              color: muted,
              opacity: subOpacity,
            }}
          >
            {props.subtitle}
          </p>
        ) : null}
      </AbsoluteFill>
    </Background>
  );
};
