/**
 * Single source of truth for the title-card prop shape. Mirrored by the tab
 * form (RemotionPanel) and validated (hybrid: strict/lenient) backend-side in
 * backend/api/routes/remotion.py::_sanitize_props.
 *
 * Declared as a `type` (not `interface`) on purpose: Remotion's
 * Player/Composition generics constrain composition props to
 * `Record<string, unknown>`, which a type-alias object literal satisfies but a
 * plain interface (no implicit index signature) does not.
 */
import type { AnimationId } from "../animations";

export type CardAnimation = AnimationId;
export type CardBackground = "solid" | "gradient";
export type DecorationSet = "leaves" | "flowers" | "mixed" | "none";
export type DecorationDensity = "none" | "low" | "med" | "high";
/** How many Lottie INSTANCES the animation layer places — independent of the
 *  SVG botanicals' `DecorationDensity` (no "none": the count only matters once
 *  at least one animation has been added). */
export type LottieDensity = "low" | "med" | "high";

export type CardPalette = {
  background: string;
  text: string;
  accent: string;
};

export type CardDecoration = {
  set: DecorationSet;
  density: DecorationDensity;
};

/** One user-chosen Lottie decoration: a library filename (e.g. "flower.json"),
 *  whether it loops, and whether to recolor it toward the palette. Loop off =
 *  play once and HOLD the final frame (so a one-shot "grow" animation settles
 *  fully grown instead of snapping back). `recolor` is per-animation (blended by
 *  `lottieRecolorAmount`); defaults to true. */
export type LottieAnimationEntry = {
  name: string;
  loop: boolean;
  recolor: boolean;
};

/** Runtime counterpart to a LottieAnimationEntry: the fetched + parsed Lottie
 *  JSON paired with that entry's loop + recolor settings. */
export type LottieRuntimeEntry = {
  data: Record<string, unknown>;
  loop: boolean;
  recolor: boolean;
};

export type CardProps = {
  title: string;
  subtitle?: string;
  /** Small uppercase kicker above the title. Optional; only GardenPremium
   *  renders it today (other cards ignore it). */
  eyebrow?: string;
  /** Word/phrase within the title to emphasize in `palette.accent`. Optional;
   *  GardenPremium-specific (other cards ignore it). */
  highlight?: string;
  animation: CardAnimation;
  palette: CardPalette;
  /** Fill treatment. Independent of `decoration` so a card can show a gradient
   *  AND botanicals at the same time. */
  background: CardBackground;
  decoration: CardDecoration;
  /** One of the curated font ids (see FONT_OPTIONS in defaults.ts). */
  fontFamily: string;
  /** Clamped 2–20 backend-side; drives durationInFrames via calculateMetadata. */
  durationInSeconds: number;
  /** Optional Lottie decorations (GardenBloom only), layered ON TOP OF the SVG
   *  botanicals — both render together. Each entry is a library filename plus
   *  its loop + recolor settings; the card places instances cycling through the
   *  list. User-edited via the panel; other cards ignore it. */
  lottieAnimations?: LottieAnimationEntry[];
  /** How many Lottie INSTANCES to place, independent of `decoration.density`
   *  (which still drives the SVG botanicals). Defaults to "low". GardenBloom-only. */
  lottieDensity?: LottieDensity;
  /** How strongly recolored Lottie decorations blend toward `palette.accent`,
   *  0..1 (0 = native colors, 1 = full palette). Applies to every animation
   *  whose per-row `recolor` is on. Defaults to 0.8. GardenBloom-only. */
  lottieRecolorAmount?: number;
  /** Runtime-only: the fetched + parsed Lottie JSON for each `lottieAnimations`
   *  entry, in the SAME order (null for a not-yet-loaded / failed entry),
   *  injected by RemotionPanel straight into the <Player> inputProps. NOT a
   *  user-edited form field and NOT carried through the render pipeline (the
   *  backend sanitizer drops it). GardenBloom layers these over the botanicals;
   *  other cards ignore them. */
  lottieData?: Array<LottieRuntimeEntry | null>;
};
