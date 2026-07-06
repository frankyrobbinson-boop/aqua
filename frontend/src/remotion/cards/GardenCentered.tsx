/**
 * GardenCentered — a centered title with an optional subtitle over a soft
 * garden wash, with sparse floating botanicals scattered around the edges.
 * Supersedes the old TitleCard. Its own light canvas, independent of the app's
 * dark theme.
 *
 * Siblings are imported by RELATIVE path: Remotion's bundler resolves this tree
 * without the app's `@/*` alias.
 */
import { AbsoluteFill } from "remotion";

import { useFadeIn, useTextEntrance } from "../animations";
import { Background } from "./Background";
import { DecorationLayer } from "./decorations";
import { mix, resolveFontFamily } from "./theme";
import type { CardProps } from "./types";

export const GardenCentered = (props: CardProps) => {
  const { palette } = props;
  const font = resolveFontFamily(props.fontFamily);
  const { style, text } = useTextEntrance(props.animation, props.title);
  const subOpacity = useFadeIn(0.5, 0.7);

  const muted = mix(palette.text, palette.background, 0.28);

  return (
    <Background
      palette={palette}
      background={props.background}
      decoration={
        <DecorationLayer
          set={props.decoration.set}
          density={props.decoration.density}
          palette={palette}
        />
      }
    >
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          padding: "0 180px",
          textAlign: "center",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontFamily: font,
            fontWeight: 800,
            fontSize: 122,
            lineHeight: 1.05,
            letterSpacing: "-0.01em",
            color: palette.text,
            ...style,
          }}
        >
          {text}
        </h1>

        {props.subtitle ? (
          <>
            <div
              style={{
                width: 120,
                height: 6,
                borderRadius: 999,
                margin: "36px 0 0",
                background: palette.accent,
                opacity: subOpacity,
              }}
            />
            <p
              style={{
                margin: "28px 0 0",
                fontFamily: font,
                fontWeight: 400,
                fontSize: 46,
                lineHeight: 1.2,
                color: muted,
                opacity: subOpacity,
              }}
            >
              {props.subtitle}
            </p>
          </>
        ) : null}
      </AbsoluteFill>
    </Background>
  );
};
