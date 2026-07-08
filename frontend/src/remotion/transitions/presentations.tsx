/**
 * Two custom @remotion/transitions presentations for the /remotion "Transitions"
 * tab, alongside the built-in fade/slide/wipe/clockWipe/flip:
 *
 *   - flowerSwipe: the entering clip B is revealed behind a soft, DIAGONAL edge (a
 *     feathered `mask-image` gradient tilted by `angle`, driven by
 *     `presentationProgress`), with a curtain of real delphinium cut-outs
 *     (public/transitions/delphinium.png) riding the leading edge and a faint
 *     `edgeColor` tint blending the cut.
 *   - flicker: the exiting A and entering B trade visibility in `count` quick
 *     counter-phase steps, always settling on B.
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

// --- flicker ---------------------------------------------------------------

export type FlickerProps = {
  /** How many on/off steps the two clips trade before settling on B. */
  count: number;
};

const FlickerPresentation: FC<
  TransitionPresentationComponentProps<FlickerProps>
> = ({ presentationProgress, presentationDirection, children, passedProps }) => {
  const count = Math.max(1, Math.round(passedProps.count));
  // Split the transition into `count` segments; alternate which clip shows,
  // arranged so the LAST segment (and thus progress 1) always lands on B.
  const seg = Math.min(count - 1, Math.floor(presentationProgress * count));
  const showB = (count - 1 - seg) % 2 === 0;
  const visible =
    presentationDirection === "entering" ? showB : !showB;
  return (
    <AbsoluteFill style={{ opacity: visible ? 1 : 0 }}>{children}</AbsoluteFill>
  );
};

export const flicker = (
  props: FlickerProps,
): TransitionPresentation<FlickerProps> => ({
  component: FlickerPresentation,
  props,
});
