/**
 * Transition registry — the UI + preview source of truth for the /remotion
 * "Transitions" tab, mirroring cards/registry.ts. Each definition carries its
 * label/description, whether it takes a direction (and the options), which extra
 * knobs it exposes, its default params, and a `build` that returns the concrete
 * @remotion/transitions presentation + timing for the preview.
 *
 * `TRANSITION_IDS` is mirrored by ALLOWED_TRANSITIONS in
 * backend/api/routes/remotion.py — keep the two in sync when adding or removing
 * a transition (same convention as CARD_IDS ↔ ALLOWED_COMPS).
 *
 * Design + preview only: nothing here touches the video render/assembly pipeline.
 */
import {
  linearTiming,
  springTiming,
  type TransitionPresentation,
  type TransitionTiming,
} from "@remotion/transitions";
import { clockWipe } from "@remotion/transitions/clock-wipe";
import { crossZoom } from "@remotion/transitions/cross-zoom";
import { crosswarp } from "@remotion/transitions/crosswarp";
import { dissolve } from "@remotion/transitions/dissolve";
import { dreamyZoom } from "@remotion/transitions/dreamy-zoom";
import { fade } from "@remotion/transitions/fade";
import { filmBurn } from "@remotion/transitions/film-burn";
import { flip, type FlipDirection } from "@remotion/transitions/flip";
import { iris } from "@remotion/transitions/iris";
import { linearBlur } from "@remotion/transitions/linear-blur";
import { ripple } from "@remotion/transitions/ripple";
import { slide, type SlideDirection } from "@remotion/transitions/slide";
import { wipe, type WipeDirection } from "@remotion/transitions/wipe";
import { zoomBlur } from "@remotion/transitions/zoom-blur";

import { blurDissolve, fadeToBlack, flowerSwipe } from "./presentations";

/** Timing curve applied to any transition. */
export type TransitionTimingId = "linear" | "spring";

/** The optional per-transition knob beyond duration/direction/timing, gated per
 *  definition via `paramKeys` (this has a bespoke control: a color picker).
 *  Generic numeric knobs go through `numericParams`. */
export type TransitionParamKey = "edgeColor";

/** Numeric knobs a transition exposes as a bounded slider in the designer. Each
 *  is a numeric key of `TransitionParams`; a definition lists the ones it uses
 *  via `numericParams` — flowerSwipe's `angle` and the Tier-B shader knobs. */
export type TransitionNumericKey =
  | "angle"
  | "rotation"
  | "strength"
  | "seed"
  | "intensity"
  | "amplitude"
  | "speed"
  | "scale"
  | "maxBlur";

/** Full knob set carried by the designer + persisted with a saved design. Each
 *  transition reads the subset it cares about; unused knobs ride along so
 *  switching types (which reseeds from `defaultParams`) stays lossless. */
export type TransitionParams = {
  timing: TransitionTimingId;
  /** Transition length in frames — the two sample clips overlap by this much. */
  durationInFrames: number;
  /** Edge/direction for slide/wipe/flip (ignored by the rest). */
  direction: string;
  /** flowerSwipe: color of the botanical reveal edge (`#rrggbb`). */
  edgeColor: string;
  /** flowerSwipe: tilt of the diagonal reveal edge, in degrees. */
  angle: number;
  /** zoomBlur: max radial rotation, in radians. */
  rotation: number;
  /** crossZoom: zoom strength (0..1). */
  strength: number;
  /** filmBurn: noise seed for the burn pattern. */
  seed: number;
  /** linearBlur / dissolve: effect intensity. */
  intensity: number;
  /** ripple: wave amplitude (px). */
  amplitude: number;
  /** ripple: wave speed. */
  speed: number;
  /** dreamyZoom: zoom scale. */
  scale: number;
  /** blurDissolve: peak defocus blur (px @1080p) at the far end of the dissolve. */
  maxBlur: number;
};

export type TransitionBuildArgs = {
  params: TransitionParams;
  width: number;
  height: number;
  fps: number;
};

/** A numeric knob rendered as a bounded slider in the designer. */
export type TransitionNumericSpec = {
  key: TransitionNumericKey;
  label: string;
  min: number;
  max: number;
  step: number;
};

export type TransitionDefinition = {
  id: string;
  label: string;
  description: string;
  /** Rendering tier. "A" = pure CSS/SVG (fade/slide/wipe/flip/clockWipe/iris/
   *  flowerSwipe) — renders anywhere. "B" = a WebGL shader
   *  (html-in-canvas): the browser preview needs Chrome and a headless render
   *  needs a GL backend (chromiumOptions.gl). Surfaced as a hint in the designer. */
  tier: "A" | "B";
  /** When true, the designer shows a direction <Select> from `directionOptions`. */
  supportsDirection: boolean;
  directionOptions?: ReadonlyArray<{ id: string; label: string }>;
  /** Extra knobs this transition exposes (drives the designer's per-custom controls). */
  paramKeys: ReadonlyArray<TransitionParamKey>;
  /** Numeric knobs shown as bounded sliders (flowerSwipe angle + shader knobs). */
  numericParams?: ReadonlyArray<TransitionNumericSpec>;
  defaultParams: TransitionParams;
  build: (args: TransitionBuildArgs) => {
    presentation: TransitionPresentation<Record<string, unknown>>;
    timing: TransitionTiming;
  };
};

// Base knob values every definition starts from; each overrides only what it
// needs so switching transitions reseeds a complete params object.
const BASE_PARAMS: TransitionParams = {
  timing: "linear",
  durationInFrames: 30,
  direction: "from-left",
  edgeColor: "#7bae5a",
  // flowerSwipe: a gentle diagonal tilt (deg).
  angle: -24,
  // Shader knobs — seeded from each @remotion/transitions factory's own default;
  // a definition overrides only the one(s) it exposes.
  rotation: Math.PI / 6,
  strength: 0.4,
  seed: 2.31,
  intensity: 0.1,
  amplitude: 100,
  speed: 50,
  scale: 1.2,
  // blurDissolve: peak defocus blur (px) — seam softness is ~half this.
  maxBlur: 36,
};

// Direction option lists offered by the designer's <Select>, per transition.
const CARDINAL_DIRECTIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "from-left", label: "From left" },
  { id: "from-right", label: "From right" },
  { id: "from-top", label: "From top" },
  { id: "from-bottom", label: "From bottom" },
];
const WIPE_DIRECTIONS: ReadonlyArray<{ id: string; label: string }> = [
  ...CARDINAL_DIRECTIONS,
  { id: "from-top-left", label: "From top-left" },
  { id: "from-top-right", label: "From top-right" },
  { id: "from-bottom-left", label: "From bottom-left" },
  { id: "from-bottom-right", label: "From bottom-right" },
];

/** Timing curve → @remotion/transitions TransitionTiming. Spring and linear both
 *  settle at `durationInFrames`, so the two-clip stage length is unaffected. */
function buildTiming(params: TransitionParams): TransitionTiming {
  const durationInFrames = Math.max(1, Math.round(params.durationInFrames));
  return params.timing === "spring"
    ? springTiming({ durationInFrames, config: { damping: 200 } })
    : linearTiming({ durationInFrames });
}

/** Widen a concrete presentation to the registry's uniform build type. Safe:
 *  TransitionSeries.Transition only reads `{component, props}`, and every
 *  presentation's props is a plain object. */
function widen<P extends Record<string, unknown>>(
  presentation: TransitionPresentation<P>,
): TransitionPresentation<Record<string, unknown>> {
  return presentation as unknown as TransitionPresentation<
    Record<string, unknown>
  >;
}

export const TRANSITIONS: readonly TransitionDefinition[] = [
  {
    id: "crossfade",
    label: "Crossfade",
    description: "A soft dissolve from clip A into clip B.",
    tier: "A",
    supportsDirection: false,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(fade()),
      timing: buildTiming(params),
    }),
  },
  {
    id: "fadeToBlack",
    label: "Fade to black",
    description: "Clip A dips to black, then clip B rises from black.",
    tier: "A",
    supportsDirection: false,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(fadeToBlack()),
      timing: buildTiming(params),
    }),
  },
  {
    id: "blurDissolve",
    label: "Blur dissolve",
    description:
      "A soft defocus crossfade — clip A blurs out and clip B blurs in through the blend, resolving into a premium dissolve.",
    tier: "A",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "maxBlur", label: "Max blur", min: 0, max: 60, step: 2 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(blurDissolve({ maxBlur: params.maxBlur })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "slide",
    label: "Slide",
    description: "Clip B slides in and pushes clip A off-frame.",
    tier: "A",
    supportsDirection: true,
    directionOptions: CARDINAL_DIRECTIONS,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(
        slide({ direction: params.direction as SlideDirection }),
      ),
      timing: buildTiming(params),
    }),
  },
  {
    id: "wipe",
    label: "Wipe",
    description: "Clip B wipes over clip A from the chosen edge.",
    tier: "A",
    supportsDirection: true,
    directionOptions: WIPE_DIRECTIONS,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(
        wipe({ direction: params.direction as WipeDirection }),
      ),
      timing: buildTiming(params),
    }),
  },
  {
    id: "clockWipe",
    label: "Clock wipe",
    description: "Clip B is revealed by a sweeping clock-hand wipe.",
    tier: "A",
    supportsDirection: false,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params, width, height }) => ({
      presentation: widen(clockWipe({ width, height })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "iris",
    label: "Iris",
    description: "Clip B is revealed through an expanding circular iris.",
    tier: "A",
    supportsDirection: false,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params, width, height }) => ({
      presentation: widen(iris({ width, height })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "flip",
    label: "Flip",
    description: "Clip A flips over to reveal clip B in 3-D.",
    tier: "A",
    supportsDirection: true,
    directionOptions: CARDINAL_DIRECTIONS,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(
        flip({ direction: params.direction as FlipDirection }),
      ),
      timing: buildTiming(params),
    }),
  },
  {
    id: "flowerSwipe",
    label: "Flower swipe",
    description:
      "Clip B is painted in behind a diagonal feathered edge as a curtain of real delphiniums sweeps across.",
    tier: "A",
    supportsDirection: false,
    paramKeys: ["edgeColor"],
    numericParams: [
      { key: "angle", label: "Angle", min: -45, max: 45, step: 1 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(
        flowerSwipe({ angle: params.angle, edgeColor: params.edgeColor }),
      ),
      timing: buildTiming(params),
    }),
  },

  // --- Tier B: WebGL shader transitions (@remotion/transitions). Rendered via
  // html-in-canvas, so the browser preview needs Chrome and a headless render
  // needs a GL backend (chromiumOptions.gl). Each knob is seeded from the
  // package factory's own default. -----------------------------------------
  {
    id: "zoomBlur",
    label: "Zoom blur",
    description: "A radial zoom-blur streaks clip A into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "rotation", label: "Rotation", min: 0, max: 1.2, step: 0.05 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(zoomBlur({ rotation: params.rotation })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "crossZoom",
    label: "Cross zoom",
    description: "Clip A zooms and blurs through into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "strength", label: "Strength", min: 0, max: 1, step: 0.05 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(crossZoom({ strength: params.strength })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "crosswarp",
    label: "Crosswarp",
    description: "Clip A warps sideways and dissolves into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(crosswarp({})),
      timing: buildTiming(params),
    }),
  },
  {
    id: "filmBurn",
    label: "Film burn",
    description: "A film-burn flare bridges clip A into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [{ key: "seed", label: "Seed", min: 0, max: 10, step: 0.1 }],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(filmBurn({ seed: params.seed })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "dissolve",
    label: "Dissolve",
    description: "Clip A burns away along a hot dissolve edge into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "intensity", label: "Intensity", min: 0, max: 2, step: 0.05 },
    ],
    defaultParams: { ...BASE_PARAMS, intensity: 1 },
    build: ({ params }) => ({
      presentation: widen(dissolve({ intensity: params.intensity })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "linearBlur",
    label: "Linear blur",
    description: "A directional motion blur carries clip A into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "intensity", label: "Intensity", min: 0, max: 1, step: 0.02 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(linearBlur({ intensity: params.intensity })),
      timing: buildTiming(params),
    }),
  },
  {
    id: "ripple",
    label: "Ripple",
    description: "A water-like ripple distorts clip A into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "amplitude", label: "Amplitude", min: 0, max: 300, step: 5 },
      { key: "speed", label: "Speed", min: 0, max: 150, step: 5 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(
        ripple({ amplitude: params.amplitude, speed: params.speed }),
      ),
      timing: buildTiming(params),
    }),
  },
  {
    id: "dreamyZoom",
    label: "Dreamy zoom",
    description: "A soft dreamy zoom melts clip A into clip B.",
    tier: "B",
    supportsDirection: false,
    paramKeys: [],
    numericParams: [
      { key: "scale", label: "Scale", min: 1, max: 2, step: 0.05 },
    ],
    defaultParams: { ...BASE_PARAMS },
    build: ({ params }) => ({
      presentation: widen(dreamyZoom({ scale: params.scale })),
      timing: buildTiming(params),
    }),
  },
];

export const TRANSITION_IDS: readonly string[] = TRANSITIONS.map((t) => t.id);

/** Look up a definition by id, falling back to the first — keeps the designer +
 *  preview total even if a stale saved id shows up. */
export function getTransition(id: string): TransitionDefinition {
  return TRANSITIONS.find((t) => t.id === id) ?? TRANSITIONS[0];
}
