/**
 * Custom @remotion/transitions presentations for the /remotion "Transitions"
 * tab, alongside the built-in fade/slide/wipe/clockWipe/flip:
 *
 *   - flowerSwipe: the entering clip B is revealed behind a soft, DIAGONAL edge (a
 *     feathered `mask-image` gradient tilted by `angle`, driven by
 *     `presentationProgress`), with a curtain of real delphinium cut-outs
 *     (public/transitions/delphinium.png) riding the leading edge and a faint
 *     `edgeColor` tint blending the cut.
 *   - fadeToBlack: clip A dips to black, then clip B rises from black (a
 *     through-black dip, not a direct A→B blend).
 *   - blurDissolve: a DEFOCUS crossfade — A blurs OUT and B blurs IN through the
 *     blend, so the seam passes through soft focus (a premium dissolve).
 *
 * Plain Remotion (no "use client"): a presentation component is rendered by
 * TransitionSeries for BOTH the exiting and entering clip (see
 * `presentationDirection`). Consumed by the browser <Player> AND the Remotion
 * bundler (via registry.ts → TransitionPreview → Root.tsx), so siblings are
 * imported by relative path.
 */
import type { FC } from "react";

import type {
  TransitionPresentation,
  TransitionPresentationComponentProps,
} from "@remotion/transitions";
import { AbsoluteFill, Img, staticFile, useVideoConfig } from "remotion";

// --- flowerSwipe -----------------------------------------------------------

export type FlowerSwipeProps = {
  /** Tilt of the diagonal reveal edge, in degrees from vertical. */
  angle: number;
  /** `#rrggbb` — a faint tint feathered along the leading edge to blend the cut. */
  edgeColor: string;
};

// The delphinium "curtain" riding the leading edge: each spike is a horizontal
// offset from the sweep edge (% frame width), a vertical nudge from centre
// (% frame height), a height (% frame height), and whether to mirror it. Fixed
// constants → the transition is fully deterministic (no random / Date.now).
const CURTAIN: ReadonlyArray<{
  dx: number;
  dy: number;
  h: number;
  flip: boolean;
}> = [
  { dx: -8, dy: 3, h: 92, flip: false },
  { dx: -1, dy: -4, h: 106, flip: true },
  { dx: 6, dy: 5, h: 88, flip: false },
];

// Off-frame margin (% frame width) so the curtain fully clears both edges at
// progress 0 and 1.
const SWEEP_MARGIN = 22;
// Feather width of the reveal edge (% along the mask-gradient axis).
const EDGE_FEATHER = 14;

const DELPHINIUM = "transitions/delphinium.png";

const FlowerSwipePresentation: FC<
  TransitionPresentationComponentProps<FlowerSwipeProps>
> = ({ presentationProgress, presentationDirection, children, passedProps }) => {
  const { height } = useVideoConfig();
  const { angle, edgeColor } = passedProps;

  // Exiting clip A stays put underneath; only the entering clip B is masked +
  // decorated, so the wipe reads as a curtain of B sweeping over A.
  if (presentationDirection === "exiting") {
    return <AbsoluteFill>{children}</AbsoluteFill>;
  }

  const p = Math.max(0, Math.min(1, presentationProgress));
  // The leading edge, in ONE numeric space shared by the mask stops and the
  // flower row, so the blooms track the feathered reveal edge as it sweeps.
  const sweep = -SWEEP_MARGIN + p * (100 + 2 * SWEEP_MARGIN);
  // ~90deg sweeps left→right; `angle` tilts the edge off vertical.
  const gradDeg = 90 + angle;
  // Behind the edge (opaque) shows B; ahead of it (transparent) still shows A.
  const maskImage = `linear-gradient(${gradDeg}deg, #000 ${
    sweep - EDGE_FEATHER
  }%, transparent ${sweep}%)`;
  // A faint colored band hugging the edge to soften the cut.
  const tint = `linear-gradient(${gradDeg}deg, transparent ${
    sweep - EDGE_FEATHER
  }%, ${edgeColor} ${sweep - EDGE_FEATHER / 2}%, transparent ${sweep + 2}%)`;

  return (
    <AbsoluteFill>
      {/* Entering clip B, revealed behind the feathered diagonal edge. */}
      <AbsoluteFill
        style={{
          maskImage,
          WebkitMaskImage: maskImage,
          maskRepeat: "no-repeat",
          WebkitMaskRepeat: "no-repeat",
        }}
      >
        {children}
      </AbsoluteFill>

      {/* Soft edge tint. */}
      <AbsoluteFill
        style={{ background: tint, opacity: 0.35, pointerEvents: "none" }}
      />

      {/* The delphinium curtain riding the leading edge. */}
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        {CURTAIN.map((f, i) => (
          <Img
            key={i}
            src={staticFile(DELPHINIUM)}
            style={{
              position: "absolute",
              left: `${sweep + f.dx}%`,
              top: `${50 + f.dy}%`,
              height: (height * f.h) / 100,
              width: "auto",
              transform: `translate(-50%, -50%) rotate(${angle}deg)${
                f.flip ? " scaleX(-1)" : ""
              }`,
              transformOrigin: "center",
            }}
          />
        ))}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const flowerSwipe = (
  props: FlowerSwipeProps,
): TransitionPresentation<FlowerSwipeProps> => ({
  component: FlowerSwipePresentation,
  props,
});

// --- fadeToBlack -----------------------------------------------------------

/**
 * fadeToBlack — a dip-to-black between clips, distinct from the crossfade `fade`
 * (which blends A directly into B with no black in between). Clip A dips to black
 * over the first half of the transition; clip B rises from black over the second
 * half, so the through-black hold lands at the midpoint. Driven by the
 * ALREADY-EASED `presentationProgress`, so the caller's timing curve shapes the dip.
 *
 * No props. The exiting clip A sits under a black veil that ramps 0→1 across the
 * first half (then holds full); the entering clip B — stacked on top by
 * TransitionSeries — stays hidden until the midpoint, then fades 0→1. Net: the
 * seam reads A → black → B.
 */
const FadeToBlackPresentation: FC<
  TransitionPresentationComponentProps<Record<string, never>>
> = ({ presentationProgress, presentationDirection, children }) => {
  const p = Math.max(0, Math.min(1, presentationProgress));

  if (presentationDirection === "exiting") {
    // A, dimming to black over the first half; black holds through the second.
    const veil = Math.min(1, p * 2);
    return (
      <AbsoluteFill>
        <AbsoluteFill>{children}</AbsoluteFill>
        <AbsoluteFill style={{ backgroundColor: "#000", opacity: veil }} />
      </AbsoluteFill>
    );
  }

  // B (on top), hidden until the midpoint, then rising from black.
  const reveal = Math.max(0, p * 2 - 1);
  return <AbsoluteFill style={{ opacity: reveal }}>{children}</AbsoluteFill>;
};

export const fadeToBlack = (): TransitionPresentation<
  Record<string, never>
> => ({
  component: FadeToBlackPresentation,
  props: {},
});

// --- blurDissolve ----------------------------------------------------------

export type BlurDissolveProps = {
  /** Peak defocus blur in px (@1080p) a clip reaches at its far end of the
   *  dissolve; the visible seam softness is roughly half this. */
  maxBlur: number;
};

/**
 * blurDissolve — a soft, DEFOCUSED crossfade: a premium dissolve where the seam
 * passes THROUGH soft focus rather than a hard blend. Mirrors the built-in
 * `fade`'s opacity handling (the exiting clip A holds opaque, the entering clip
 * B fades in on top), but blurs A OUT (0→max as it is covered) and B IN (max→0
 * as it arrives), so the cut reads sharp → soft → sharp. A small overscan
 * `scale` hides the transparent edge-bleed a CSS `blur()` shows at the frame
 * border. Driven by the ALREADY-EASED `presentationProgress`, so the caller's
 * timing curve shapes the dissolve.
 */
const BlurDissolvePresentation: FC<
  TransitionPresentationComponentProps<BlurDissolveProps>
> = ({ presentationProgress, presentationDirection, children, passedProps }) => {
  const { height } = useVideoConfig();
  const p = Math.max(0, Math.min(1, presentationProgress));
  const { maxBlur } = passedProps;

  const isEntering = presentationDirection === "entering";
  // A blurs OUT as it is covered; B blurs IN as it resolves.
  const blur = isEntering ? maxBlur * (1 - p) : maxBlur * p;
  // Overscan just enough to push the softened border off-frame (a blur() bleeds
  // transparent pixels ~`blur` px inward at every edge).
  const scale = 1 + (2 * blur) / height;

  return (
    <AbsoluteFill
      style={{
        filter: `blur(${blur.toFixed(2)}px)`,
        transform: `scale(${scale.toFixed(4)})`,
        // Exiting A holds opaque (like `fade`); entering B fades in on top.
        ...(isEntering ? { opacity: p } : null),
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export const blurDissolve = (
  props: BlurDissolveProps,
): TransitionPresentation<BlurDissolveProps> => ({
  component: BlurDissolvePresentation,
  props,
});
