/**
 * Floral card style — variant table. One entry per registered floral slide id
 * (the slide's `variant` prop keys into this map); every entry drives the SAME
 * parameterized <FloralCard>. An entry picks a text LAYOUT archetype and lists
 * the botanical LAYERS to stack over the shared paper texture.
 *
 * Each layer's `src` + normalized bbox (`x/y/w/h`, fractions of the 1920x1080
 * canvas) are TRANSCRIBED from public/cardstyle/manifest.json — regenerate the
 * assets + manifest with `node scripts/extract-floral-assets.mjs` and re-copy
 * the numbers here if the crops change. `delay`/`dir`/`driftPx` drive the
 * staggered per-layer entrance (useLayerEntrance); `sway`/`phase` add a slow,
 * out-of-sync idle rotation once settled.
 */
import type { LayerEntranceDir } from "../../animations";

/** Text archetype: a centered hero title, or a title anchored to the left with
 *  the botanicals massed on the right. */
export type FloralLayout = "center" | "left";

export type FloralLayer = {
  /** Filename under public/cardstyle/botanicals. */
  src: string;
  /** Normalized content bbox on the 1920x1080 canvas (from the manifest). */
  x: number;
  y: number;
  w: number;
  h: number;
  /** Entrance stagger (seconds) + drift direction/distance. */
  delay: number;
  dir: LayerEntranceDir;
  driftPx?: number;
  /** Idle sway amplitude (degrees) + phase offset, for a gentle out-of-sync
   *  drift once the entrance settles. 0 = still. */
  sway?: number;
  phase?: number;
};

export type FloralVariant = {
  layout: FloralLayout;
  layers: readonly FloralLayer[];
};

export const FLORAL_VARIANTS: Record<string, FloralVariant> = {
  // Slide 1 — "Flora." centered hero. Each layer is an INDIVIDUAL flower
  // segmented from the slide (see extract-floral-assets.mjs); they drift inward
  // from their nearest edge, staggered, to frame the centered title.
  FloralSlide01: {
    layout: "center",
    layers: [
      { src: "slide01-01.png", x: 0, y: 0, w: 0.2083, h: 0.5991, delay: 0, dir: "right", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide01-02.png", x: 0.2414, y: 0, w: 0.4073, h: 0.3292, delay: 0.025, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide01-03.png", x: 0.6823, y: 0, w: 0.049, h: 0.1417, delay: 0.05, dir: "down", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide01-04.png", x: 0.7188, y: 0, w: 0.0461, h: 0.2343, delay: 0.075, dir: "down", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide01-05.png", x: 0.7615, y: 0, w: 0.0367, h: 0.1019, delay: 0.1, dir: "down", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide01-06.png", x: 0.807, y: 0, w: 0.193, h: 0.2681, delay: 0.125, dir: "left", driftPx: 16, sway: 0.5, phase: 2.22 },
      { src: "slide01-07.png", x: 0.8924, y: 0.2648, w: 0.1076, h: 0.162, delay: 0.15, dir: "left", driftPx: 16, sway: 0.4, phase: 3.92 },
      { src: "slide01-08.png", x: 0.9758, y: 0.4338, w: 0.0242, h: 0.1407, delay: 0.175, dir: "left", driftPx: 16, sway: 0.55, phase: 5.62 },
      { src: "slide01-09.png", x: 0.788, y: 0.4514, w: 0.212, h: 0.5486, delay: 0.2, dir: "left", driftPx: 16, sway: 0.45, phase: 1.03 },
      { src: "slide01-10.png", x: 0, y: 0.6449, w: 0.1385, h: 0.3551, delay: 0.225, dir: "right", driftPx: 16, sway: 0.6, phase: 2.73 },
      { src: "slide01-11.png", x: 0.706, y: 0.7486, w: 0.149, h: 0.2514, delay: 0.25, dir: "up", driftPx: 16, sway: 0.5, phase: 4.43 },
      { src: "slide01-12.png", x: 0.1424, y: 0.7542, w: 0.2411, h: 0.2458, delay: 0.275, dir: "up", driftPx: 16, sway: 0.4, phase: 6.13 },
      { src: "slide01-13.png", x: 0.4878, y: 0.813, w: 0.1586, h: 0.187, delay: 0.3, dir: "up", driftPx: 16, sway: 0.55, phase: 1.55 },
      { src: "slide01-14.png", x: 0.6909, y: 0.8375, w: 0.0987, h: 0.1625, delay: 0.325, dir: "up", driftPx: 16, sway: 0.45, phase: 3.25 },
      { src: "slide01-15.png", x: 0.4182, y: 0.8843, w: 0.074, h: 0.1157, delay: 0.35, dir: "up", driftPx: 16, sway: 0.6, phase: 4.95 },
    ],
  },
  // Slide 2 — heading-left. The title (and optional body) sit on the left; the
  // INDIVIDUAL flowers segmented from the slide mass down the right edge, each
  // drifting inward on its own staggered delay.
  FloralSlide02: {
    layout: "left",
    layers: [
      { src: "slide02-01.png", x: 0.5802, y: 0, w: 0.2391, h: 0.4116, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide02-02.png", x: 0.8302, y: 0, w: 0.1698, h: 0.4884, delay: 0.117, dir: "left", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide02-03.png", x: 0.6484, y: 0.4551, w: 0.3516, h: 0.5449, delay: 0.233, dir: "left", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide02-04.png", x: 0.5547, y: 0.6236, w: 0.0904, h: 0.3764, delay: 0.35, dir: "up", driftPx: 16, sway: 0.45, phase: 5.1 },
    ],
  },
};

/** Fallback when a card's `variant` is missing/unknown (lenient, like the other
 *  style enums). Slide 1's centered hero is the neutral default. */
export const DEFAULT_FLORAL_VARIANT: FloralVariant = FLORAL_VARIANTS.FloralSlide01;

/** Resolve a `variant` id to its layout+layers, falling back to the default. */
export function resolveFloralVariant(id: string | undefined): FloralVariant {
  return (id && FLORAL_VARIANTS[id]) || DEFAULT_FLORAL_VARIANT;
}
