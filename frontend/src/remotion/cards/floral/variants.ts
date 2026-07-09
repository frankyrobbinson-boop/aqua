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

/** Text archetype: a centered hero title, or a title anchored to ONE side with
 *  the botanicals massed on the OTHER ("left" = heading left / flowers right;
 *  "right" = heading right / flowers left). */
export type FloralLayout = "center" | "left" | "right";

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
  // Slide 3 — "Biological Diversity." heading-right; the botanicals mass down the left.
  FloralSlide03: {
    layout: "right",
    layers: [
      { src: "slide03-01.png", x: 0, y: 0, w: 0.269, h: 0.6912, delay: 0, dir: "right", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide03-02.png", x: 0.232, y: 0.162, w: 0.187, h: 0.838, delay: 0.175, dir: "right", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide03-03.png", x: 0, y: 0.7282, w: 0.2411, h: 0.2718, delay: 0.35, dir: "up", driftPx: 16, sway: 0.55, phase: 3.4 },
    ],
  },
  // Slide 4 — "Ecological Function." heading-left; the botanicals mass down the right.
  FloralSlide04: {
    layout: "left",
    layers: [
      { src: "slide04-01.png", x: 0.6732, y: 0, w: 0.3268, h: 0.5449, delay: 0, dir: "left", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide04-02.png", x: 0.5659, y: 0.5083, w: 0.2073, h: 0.2157, delay: 0.175, dir: "left", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide04-03.png", x: 0.4943, y: 0.5375, w: 0.5057, h: 0.4625, delay: 0.35, dir: "up", driftPx: 16, sway: 0.55, phase: 3.4 },
    ],
  },
  // Slide 5 — "Endemic Flora." heading-right; the botanicals mass down the left.
  FloralSlide05: {
    layout: "right",
    layers: [
      { src: "slide05-01.png", x: 0.276, y: 0, w: 0.0375, h: 0.2005, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide05-02.png", x: 0.3086, y: 0, w: 0.0654, h: 0.2662, delay: 0.05, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide05-03.png", x: 0.3336, y: 0, w: 0.0508, h: 0.1185, delay: 0.1, dir: "down", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide05-04.png", x: 0, y: 0.0556, w: 0.2349, h: 0.4, delay: 0.15, dir: "down", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide05-05.png", x: 0.2685, y: 0.2972, w: 0.0708, h: 0.1269, delay: 0.2, dir: "right", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide05-06.png", x: 0.1792, y: 0.381, w: 0.2411, h: 0.3838, delay: 0.25, dir: "right", driftPx: 16, sway: 0.5, phase: 2.22 },
      { src: "slide05-07.png", x: 0, y: 0.5407, w: 0.2133, h: 0.438, delay: 0.3, dir: "up", driftPx: 16, sway: 0.4, phase: 3.92 },
      { src: "slide05-08.png", x: 0.2094, y: 0.7292, w: 0.2292, h: 0.2708, delay: 0.35, dir: "up", driftPx: 16, sway: 0.55, phase: 5.62 },
    ],
  },
  // Slide 6 — "Economic Importance." heading-left; the botanicals mass down the right.
  FloralSlide06: {
    layout: "left",
    layers: [
      { src: "slide06-01.png", x: 0.6654, y: 0, w: 0.3346, h: 1, delay: 0, dir: "left", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide06-02.png", x: 0.5005, y: 0.5366, w: 0.276, h: 0.4634, delay: 0.35, dir: "up", driftPx: 16, sway: 0.4, phase: 1.7 },
    ],
  },
  // Slide 7 — "Medicinal Flora." heading-right; the botanicals mass down the left.
  FloralSlide07: {
    layout: "right",
    layers: [
      { src: "slide07-01.png", x: 0.1656, y: 0, w: 0.2258, h: 0.8269, delay: 0, dir: "right", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide07-02.png", x: 0, y: 0.0764, w: 0.1492, h: 0.606, delay: 0.117, dir: "right", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide07-03.png", x: 0, y: 0.6829, w: 0.2086, h: 0.3171, delay: 0.233, dir: "up", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide07-04.png", x: 0.2146, y: 0.7903, w: 0.2294, h: 0.2097, delay: 0.35, dir: "up", driftPx: 16, sway: 0.45, phase: 5.1 },
    ],
  },
  // Slide 8 — "Flora Conservation." heading-left; the botanicals mass down the right.
  FloralSlide08: {
    layout: "left",
    layers: [
      { src: "slide08-01.png", x: 0.5932, y: 0, w: 0.1146, h: 0.3208, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide08-02.png", x: 0.7044, y: 0, w: 0.2956, h: 0.4139, delay: 0.175, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide08-03.png", x: 0.4857, y: 0.4181, w: 0.5143, h: 0.5819, delay: 0.35, dir: "left", driftPx: 16, sway: 0.55, phase: 3.4 },
    ],
  },
  // Slide 9 — "Human Impact." heading-right; the botanicals mass down the left.
  FloralSlide09: {
    layout: "right",
    layers: [
      { src: "slide09-01.png", x: 0.1909, y: 0, w: 0.2518, h: 0.55, delay: 0, dir: "right", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide09-02.png", x: 0, y: 0.0463, w: 0.2326, h: 0.4731, delay: 0.117, dir: "right", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide09-03.png", x: 0.2854, y: 0.431, w: 0.1466, h: 0.569, delay: 0.233, dir: "right", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide09-04.png", x: 0.0255, y: 0.5611, w: 0.2354, h: 0.4389, delay: 0.35, dir: "up", driftPx: 16, sway: 0.45, phase: 5.1 },
    ],
  },
  // Slide 10 — "Flora and Culture." heading-left; the botanicals mass down the right.
  FloralSlide10: {
    layout: "left",
    layers: [
      { src: "slide10-01.png", x: 0.8036, y: 0.0088, w: 0.1964, h: 0.5269, delay: 0, dir: "left", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide10-02.png", x: 0.5042, y: 0.1204, w: 0.2977, h: 0.5852, delay: 0.07, dir: "left", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide10-03.png", x: 0.712, y: 0.5907, w: 0.288, h: 0.4093, delay: 0.14, dir: "up", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide10-04.png", x: 0.5227, y: 0.6634, w: 0.1474, h: 0.3366, delay: 0.21, dir: "up", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide10-05.png", x: 0.6161, y: 0.8968, w: 0.1187, h: 0.1032, delay: 0.28, dir: "up", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide10-06.png", x: 0.4594, y: 0.9014, w: 0.1021, h: 0.0986, delay: 0.35, dir: "up", driftPx: 16, sway: 0.5, phase: 2.22 },
    ],
  },
  // Slide 11 — "Aquatic Flora." heading-right; the botanicals mass down the left.
  FloralSlide11: {
    layout: "right",
    layers: [
      { src: "slide11-01.png", x: 0, y: 0, w: 0.2073, h: 0.2093, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide11-02.png", x: 0.2307, y: 0, w: 0.0516, h: 0.1944, delay: 0.058, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide11-03.png", x: 0.2891, y: 0, w: 0.0164, h: 0.1931, delay: 0.117, dir: "down", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide11-04.png", x: 0.3211, y: 0, w: 0.0964, h: 0.1542, delay: 0.175, dir: "down", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide11-05.png", x: 0.0109, y: 0.2259, w: 0.187, h: 0.7741, delay: 0.233, dir: "right", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide11-06.png", x: 0.2359, y: 0.2394, w: 0.2039, h: 0.3514, delay: 0.292, dir: "right", driftPx: 16, sway: 0.5, phase: 2.22 },
      { src: "slide11-07.png", x: 0.1477, y: 0.5727, w: 0.3206, h: 0.4273, delay: 0.35, dir: "up", driftPx: 16, sway: 0.4, phase: 3.92 },
    ],
  },
  // Slide 12 — "Flowers and Pollination." heading-left; the botanicals mass down the right.
  FloralSlide12: {
    layout: "left",
    layers: [
      { src: "slide12-01.png", x: 0.6849, y: 0, w: 0.2562, h: 0.394, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide12-02.png", x: 0.801, y: 0, w: 0.0346, h: 0.0407, delay: 0.088, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide12-03.png", x: 0.751, y: 0.2079, w: 0.249, h: 0.7912, delay: 0.175, dir: "left", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide12-04.png", x: 0.5602, y: 0.4546, w: 0.2, h: 0.5454, delay: 0.262, dir: "left", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide12-05.png", x: 0.6979, y: 0.9713, w: 0.0453, h: 0.0287, delay: 0.35, dir: "up", driftPx: 16, sway: 0.6, phase: 0.52 },
    ],
  },
  // Slide 13 — "Flora Adaptation." heading-right; the botanicals mass down the left.
  FloralSlide13: {
    layout: "right",
    layers: [
      { src: "slide13-01.png", x: 0, y: 0, w: 0.0573, h: 0.1741, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide13-02.png", x: 0.076, y: 0, w: 0.2581, h: 0.3611, delay: 0.07, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide13-03.png", x: 0, y: 0.2375, w: 0.2143, h: 0.319, delay: 0.14, dir: "right", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide13-04.png", x: 0, y: 0.2648, w: 0.0242, h: 0.0421, delay: 0.21, dir: "right", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide13-05.png", x: 0.1984, y: 0.4273, w: 0.1362, h: 0.5727, delay: 0.28, dir: "right", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide13-06.png", x: 0, y: 0.5722, w: 0.1854, h: 0.3991, delay: 0.35, dir: "up", driftPx: 16, sway: 0.5, phase: 2.22 },
    ],
  },
  // Slide 14 — "Flora Reforestation." heading-left; the botanicals mass down the right.
  FloralSlide14: {
    layout: "left",
    layers: [
      { src: "slide14-01.png", x: 0.5711, y: 0, w: 0.2029, h: 0.287, delay: 0, dir: "down", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide14-02.png", x: 0.7565, y: 0.056, w: 0.2435, h: 0.6278, delay: 0.117, dir: "left", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide14-03.png", x: 0.4852, y: 0.5731, w: 0.3042, h: 0.4269, delay: 0.233, dir: "up", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide14-04.png", x: 0.7742, y: 0.712, w: 0.2258, h: 0.288, delay: 0.35, dir: "up", driftPx: 16, sway: 0.45, phase: 5.1 },
    ],
  },
  // Slide 15 — "Thanks." centered hero; the botanicals ring the border.
  FloralSlide15: {
    layout: "center",
    layers: [
      { src: "slide15-01.png", x: 0, y: 0, w: 0.4091, h: 0.5991, delay: 0, dir: "right", driftPx: 16, sway: 0.5, phase: 0 },
      { src: "slide15-02.png", x: 0.4456, y: 0, w: 0.2031, h: 0.219, delay: 0.025, dir: "down", driftPx: 16, sway: 0.4, phase: 1.7 },
      { src: "slide15-03.png", x: 0.6823, y: 0, w: 0.049, h: 0.1417, delay: 0.05, dir: "left", driftPx: 16, sway: 0.55, phase: 3.4 },
      { src: "slide15-04.png", x: 0.7188, y: 0, w: 0.0461, h: 0.2343, delay: 0.075, dir: "left", driftPx: 16, sway: 0.45, phase: 5.1 },
      { src: "slide15-05.png", x: 0.7615, y: 0, w: 0.0367, h: 0.1019, delay: 0.1, dir: "left", driftPx: 16, sway: 0.6, phase: 0.52 },
      { src: "slide15-06.png", x: 0.807, y: 0, w: 0.193, h: 0.2681, delay: 0.125, dir: "left", driftPx: 16, sway: 0.5, phase: 2.22 },
      { src: "slide15-07.png", x: 0.8924, y: 0.2648, w: 0.1076, h: 0.162, delay: 0.15, dir: "left", driftPx: 16, sway: 0.4, phase: 3.92 },
      { src: "slide15-08.png", x: 0.9758, y: 0.4338, w: 0.0242, h: 0.1407, delay: 0.175, dir: "left", driftPx: 16, sway: 0.55, phase: 5.62 },
      { src: "slide15-09.png", x: 0.788, y: 0.4514, w: 0.212, h: 0.5486, delay: 0.2, dir: "left", driftPx: 16, sway: 0.45, phase: 1.04 },
      { src: "slide15-10.png", x: 0, y: 0.6449, w: 0.1385, h: 0.3551, delay: 0.225, dir: "right", driftPx: 16, sway: 0.6, phase: 2.74 },
      { src: "slide15-11.png", x: 0.706, y: 0.7486, w: 0.149, h: 0.2514, delay: 0.25, dir: "left", driftPx: 16, sway: 0.5, phase: 4.44 },
      { src: "slide15-12.png", x: 0.1424, y: 0.7542, w: 0.2411, h: 0.2458, delay: 0.275, dir: "right", driftPx: 16, sway: 0.4, phase: 6.14 },
      { src: "slide15-13.png", x: 0.4878, y: 0.813, w: 0.1586, h: 0.187, delay: 0.3, dir: "up", driftPx: 16, sway: 0.55, phase: 1.56 },
      { src: "slide15-14.png", x: 0.6909, y: 0.8375, w: 0.0987, h: 0.1625, delay: 0.325, dir: "left", driftPx: 16, sway: 0.45, phase: 3.26 },
      { src: "slide15-15.png", x: 0.4182, y: 0.8843, w: 0.074, h: 0.1157, delay: 0.35, dir: "up", driftPx: 16, sway: 0.6, phase: 4.96 },
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
