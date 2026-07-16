/**
 * FloralTag — the workhorse OST overlay: a plain fact on a small paper chip
 * (channel paper), the fact set at ONE uniform size in the channel BODY font +
 * the scheme ink, with a Phosphor icon (same ink) as the focal accent to the LEFT
 * of the text — it REPLACED the old corner sprig. A single underline (same ink)
 * spans the FULL WIDTH of the text and DRAWS ON left→right (~0.3s) once the chip
 * has landed ("6 hours of sun", "Divide every 2-3 years").
 *
 * Reads its whole look from channel tokens (palette / fontFamily / icon via
 * PhosphorIcon + PaperChip). The channel-scoped `invert` flag picks the color
 * scheme (cream chip + plum ink, or the tokens swapped: plum chip + cream ink) —
 * resolveOverlayScheme derives BOTH from the same palette, and the chip surface,
 * fact text, underline, and icon tint all read the same `ink`, so they invert
 * together. Swap the tokens and it restyles. Motion is the shared OST grammar
 * (useOverlayLifecycle): slide up 8px + fade in ~0.4s, hold dead-still, fade out
 * ~0.25s at the end, plus the underline draw-on (useDrawOn). Anchored upper-third
 * / side, never the bottom band. Plain Remotion (no "use client"); siblings
 * imported by relative path.
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

export const FloralTag = (props: OverlayProps) => {
  const font = resolveFontFamily(props.fontFamily);
  const { opacity, translateY, enterFrames } = useOverlayLifecycle();
  // The underline draws on AFTER the chip lands (delay = the entrance length).
  const draw = useDrawOn(enterFrames);
  const scheme = resolveOverlayScheme(
    props.palette,
    props.invert ?? false,
    props.bodyColor,
  );

  return (
    <AbsoluteFill>
      {/* Design-render only: the footage still, drawn behind the overlay. */}
      {props.backgroundSrc ? (
        <Img src={staticFile(props.backgroundSrc)} style={COVER} />
      ) : null}

      <AbsoluteFill style={anchorFillStyle(props.position ?? "top-left")}>
        <div style={{ opacity, transform: `translateY(${translateY}px)` }}>
          <PaperChip scheme={scheme} style={{ maxWidth: 880 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
              {props.icon ? (
                <PhosphorIcon name={props.icon} color={scheme.ink} size={58} />
              ) : null}

              {/* Uniform-size fact + a full-width underline that draws on
                  left→right beneath the WHOLE text (same idiom as
                  MeasurementStamp). The underline is absolutely positioned in a
                  shrink-to-text wrapper, so it spans exactly the text's left→right
                  edges (never the icon) and adds no layout height — the row's
                  alignItems:center keeps the icon centered on the TEXT line. */}
              <span style={{ position: "relative", display: "inline-block" }}>
                <span
                  style={{
                    display: "block",
                    fontFamily: font,
                    fontSize: 54,
                    lineHeight: 1.12,
                    color: scheme.ink,
                    letterSpacing: "-0.01em",
                    textWrap: "balance",
                  }}
                >
                  {props.fact}
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
            </div>
          </PaperChip>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
