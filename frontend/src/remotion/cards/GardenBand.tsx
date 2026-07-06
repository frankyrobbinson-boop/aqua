/**
 * GardenBand — the title sits in the upper-middle over a soft accent band along
 * the bottom, where a row of botanicals nestles and sways. Count scales with
 * decoration density; `set` picks the shapes. Its own light canvas.
 *
 * Siblings are imported by RELATIVE path (no `@/*` alias in the Remotion bundle).
 */
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { useFadeIn, useTextEntrance } from "../animations";
import { Background } from "./Background";
import { Flower, Leaf, Sprig } from "./decorations";
import { mix, resolveFontFamily } from "./theme";
import type {
  CardDecoration,
  CardPalette,
  CardProps,
  DecorationDensity,
  DecorationSet,
} from "./types";

type BandSlot = {
  left: number; // %
  bottom: number; // px
  size: number; // px
  phase: number; // rad
};

// Ordered so the first few (low density) stay spread across the width.
const BAND_SLOTS: readonly BandSlot[] = [
  { left: 12, bottom: 66, size: 132, phase: 0.0 },
  { left: 50, bottom: 86, size: 148, phase: 2.0 },
  { left: 88, bottom: 70, size: 128, phase: 1.6 },
  { left: 30, bottom: 42, size: 112, phase: 1.0 },
  { left: 70, bottom: 46, size: 112, phase: 0.6 },
  { left: 21, bottom: 122, size: 96, phase: 2.6 },
  { left: 61, bottom: 124, size: 96, phase: 1.3 },
  { left: 80, bottom: 120, size: 92, phase: 0.3 },
];

const DENSITY_COUNT: Record<DecorationDensity, number> = {
  none: 0,
  low: 3,
  med: 5,
  high: 8,
};

const SWAY_SPEED = 1.0;
const SWAY_DEG = 4;

function bandKind(set: DecorationSet, i: number): "leaf" | "sprig" | "flower" {
  if (set === "flowers") return "flower";
  if (set === "mixed") return (["flower", "leaf", "sprig"] as const)[i % 3];
  return i % 2 === 0 ? "leaf" : "sprig";
}

function BottomBand({
  palette,
  decoration,
}: {
  palette: CardPalette;
  decoration: CardDecoration;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const bandStrong = mix(palette.accent, palette.background, 0.62);
  const bandSoft = mix(palette.accent, palette.background, 0.4);

  const count =
    decoration.set === "none"
      ? 0
      : DENSITY_COUNT[decoration.density] ?? DENSITY_COUNT.low;

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 300,
          background: `linear-gradient(to top, ${bandStrong} 0%, ${bandSoft} 55%, transparent 100%)`,
        }}
      />
      {BAND_SLOTS.slice(0, count).map((slot, i) => {
        const sway = Math.sin(t * SWAY_SPEED + slot.phase) * SWAY_DEG;
        const kind = bandKind(decoration.set, i);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${slot.left}%`,
              bottom: slot.bottom,
              transform: `translateX(-50%) rotate(${sway}deg)`,
            }}
          >
            {kind === "flower" ? (
              <Flower palette={palette} size={slot.size} />
            ) : kind === "sprig" ? (
              <Sprig palette={palette} size={slot.size} />
            ) : (
              <Leaf palette={palette} size={slot.size} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export const GardenBand = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const { style, text } = useTextEntrance(props.animation, props.title);
  const subOpacity = useFadeIn(0.5, 0.7);

  const muted = mix(palette.text, palette.background, 0.28);

  return (
    <Background
      palette={palette}
      background={props.background}
      decoration={<BottomBand palette={palette} decoration={props.decoration} />}
    >
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          padding: "0 200px 320px",
          textAlign: "center",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontFamily: font,
            fontWeight: 800,
            fontSize: 114,
            lineHeight: 1.06,
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
              fontSize: 44,
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
