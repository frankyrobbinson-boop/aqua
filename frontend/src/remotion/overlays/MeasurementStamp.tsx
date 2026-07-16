/**
 * MeasurementStamp — the number-hero OST overlay: for a fact that contains a
 * NUMBER ("Plant 2 inches deep", "Depth: 1-2 in"), it splits the phrase around
 * its first numeric token and renders the number LARGE in the channel display
 * font (the scheme INK), the rest of the phrase BESIDE it (the scheme BODY) —
 * sized closer to the number than before, so the phrase reads as part of the
 * stamp — plus a thin underline (same ink) that DRAWS ON left→right (~0.3s) under
 * the number once the chip has landed, and a Phosphor icon (same ink) leading the
 * row as the focal accent (it REPLACED the old corner sprig). Sits on the SAME
 * PaperChip as FloralTag (the legibility surface, so the number reads over a
 * bright background too).
 *
 * Reads its whole look from channel tokens (palette / fontFamily / bodyColor /
 * icon). The channel-scoped `invert` flag picks the scheme (cream chip + plum ink
 * or the tokens swapped: plum chip + cream ink); resolveOverlayScheme derives
 * BOTH from the same palette and the number, underline, and icon all read the
 * same `ink`, so they invert together. Motion is the shared OST grammar
 * (useOverlayLifecycle) plus the underline draw-on (useDrawOn). Anchored
 * upper-third / side, never the bottom band. Plain Remotion; siblings imported by
 * relative path.
 */
import type { CSSProperties } from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";

import { resolveFontFamily } from "../cards/theme";
import { anchorFillStyle } from "./anchor";
import { useDrawOn, useOverlayLifecycle } from "./animation";
import { PaperChip } from "./PaperChip";
import { PhosphorIcon } from "./PhosphorIcon";
import { resolveOverlayScheme } from "./scheme";
import type { OverlayProps } from "./types";

/** Full-bleed cover style for the design-render background still. */
const COVER: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

// First numeric token: an integer/decimal, optionally a range ("1-2", "2–3").
const NUMBER_RE = /\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?/;

/** Split a fact into [before, number, after] around its first numeric token.
 *  No number → the whole phrase is returned as `before` with an empty `number`
 *  (the component then renders the phrase as a plain hero, defensively). */
function splitAroundNumber(fact: string): {
  before: string;
  number: string;
  after: string;
} {
  const m = fact.match(NUMBER_RE);
  if (!m || m.index == null) return { before: fact, number: "", after: "" };
  return {
    before: fact.slice(0, m.index).trim(),
    number: m[0].replace(/\s+/g, ""),
    after: fact.slice(m.index + m[0].length).trim(),
  };
}

/** Side text (before / after the number). Sized closer to the number now
 *  (was 40) so the phrase reads as part of the stamp, not a caption. */
const sideStyle = (color: string): CSSProperties => ({
  fontSize: 46,
  lineHeight: 1.1,
  color,
  letterSpacing: "-0.01em",
  paddingBottom: 14,
});

export const MeasurementStamp = (props: OverlayProps) => {
  const font = resolveFontFamily(props.fontFamily);
  const { opacity, translateY, enterFrames } = useOverlayLifecycle();
  // The underline draws on AFTER the chip lands (delay = the entrance length).
  const draw = useDrawOn(enterFrames);
  const scheme = resolveOverlayScheme(
    props.palette,
    props.invert ?? false,
    props.bodyColor,
  );
  const { before, number, after } = splitAroundNumber(props.fact);

  return (
    <AbsoluteFill>
      {/* Design-render only: the footage still, drawn behind the overlay. */}
      {props.backgroundSrc ? (
        <Img src={staticFile(props.backgroundSrc)} style={COVER} />
      ) : null}

      <AbsoluteFill style={anchorFillStyle(props.position ?? "top-left")}>
        <div style={{ opacity, transform: `translateY(${translateY}px)` }}>
          <PaperChip scheme={scheme} style={{ maxWidth: 980 }}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: 16,
                fontFamily: font,
              }}
            >
              {/* Focal accent: the icon leads the row (vertically centered on
                  the number), tinted the scheme ink. */}
              {props.icon ? (
                <PhosphorIcon
                  name={props.icon}
                  color={scheme.ink}
                  size={64}
                  style={{ alignSelf: "center", marginRight: 4 }}
                />
              ) : null}

              {number ? (
                <>
                  {before ? (
                    <span style={sideStyle(scheme.body)}>{before}</span>
                  ) : null}

                  {/* The number (hero) + its draw-on underline. */}
                  <span style={{ position: "relative", display: "inline-block" }}>
                    <span
                      style={{
                        display: "block",
                        fontSize: 104,
                        lineHeight: 0.9,
                        color: scheme.ink,
                        letterSpacing: "-0.02em",
                      }}
                    >
                      {number}
                    </span>
                    <span
                      style={{
                        position: "absolute",
                        left: 0,
                        bottom: -8,
                        height: 5,
                        width: "100%",
                        backgroundColor: scheme.ink,
                        borderRadius: 3,
                        transform: `scaleX(${draw})`,
                        transformOrigin: "left center",
                      }}
                    />
                  </span>

                  {after ? (
                    <span style={sideStyle(scheme.body)}>{after}</span>
                  ) : null}
                </>
              ) : (
                // Defensive: a stamp with no number renders the phrase as a hero.
                <span
                  style={{
                    fontSize: 76,
                    lineHeight: 1.0,
                    color: scheme.ink,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {props.fact}
                </span>
              )}
            </div>
          </PaperChip>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
