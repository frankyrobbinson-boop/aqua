/**
 * Garden defaults + the form option lists the /remotion tab renders its
 * dropdowns from. `CARD_DEFAULTS` is the single starting state for the panel's
 * `props` and every <Composition>'s defaultProps, so preview, render, and the
 * form all begin in lockstep.
 */
import { ANIMATION_OPTIONS } from "../animations";
import type {
  CardBackground,
  CardDecoration,
  CardProps,
  DecorationDensity,
  DecorationSet,
  LottieDensity,
} from "./types";
import { DEFAULT_FONT_ID } from "./theme";

// Re-exported so the form has one import site for every option list.
export { ANIMATION_OPTIONS };

export const FONT_OPTIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "nunito", label: "Nunito · rounded" },
  { id: "quicksand", label: "Quicksand · geometric" },
  { id: "fraunces", label: "Fraunces · serif" },
];

export const BACKGROUND_OPTIONS: ReadonlyArray<{
  id: CardBackground;
  label: string;
}> = [
  { id: "gradient", label: "Gradient" },
  { id: "solid", label: "Solid" },
];

export const DECORATION_SETS: ReadonlyArray<{ id: DecorationSet; label: string }> = [
  { id: "leaves", label: "Leaves" },
  { id: "flowers", label: "Flowers" },
  { id: "mixed", label: "Mixed" },
  { id: "none", label: "None" },
];

export const DENSITY_OPTIONS: ReadonlyArray<{
  id: DecorationDensity;
  label: string;
}> = [
  { id: "none", label: "None" },
  { id: "low", label: "Low" },
  { id: "med", label: "Medium" },
  { id: "high", label: "High" },
];

// Lottie instance-count options (GardenBloom's animation layer). Distinct from
// DENSITY_OPTIONS: no "none" — the count only matters once the user has added
// at least one animation.
export const LOTTIE_DENSITY_OPTIONS: ReadonlyArray<{
  id: LottieDensity;
  label: string;
}> = [
  { id: "low", label: "Low" },
  { id: "med", label: "Medium" },
  { id: "high", label: "High" },
];

const DEFAULT_DECORATION: CardDecoration = { set: "leaves", density: "low" };

export const CARD_DEFAULTS: CardProps = {
  title: "5 Perennials That Bloom for Years",
  subtitle: "A quick garden guide",
  animation: "rise",
  palette: {
    background: "#e9f1e4",
    text: "#2f4a34",
    accent: "#7bae5a",
  },
  background: "gradient",
  decoration: DEFAULT_DECORATION,
  fontFamily: DEFAULT_FONT_ID,
  durationInSeconds: 5,
};

/**
 * Per-card starting overrides, merged onto CARD_DEFAULTS by Root.tsx's
 * defaultProps and by the panel when you switch cards. Lets a card boot with
 * its own signature look (e.g. GardenPremium's muted palette + kicker) while
 * every card still shares one base. Keyed by registry card id.
 */
export const CARD_DEFAULT_OVERRIDES: Partial<
  Record<string, Partial<CardProps>>
> = {
  GardenPremium: {
    // Warm neutral + desaturated green — sophisticated, not flat bright green.
    palette: {
      background: "#f4f1e8",
      text: "#2f3b2b",
      accent: "#93a97e",
    },
    eyebrow: "GARDEN GUIDE",
  },
  GardenBloom: {
    // Soft sunlit warm-green canvas, deep readable garden-green text, and a warm
    // floral rose accent — foliage greens derive from the text color, blooms +
    // the highlight word from the accent. Boots lush (mixed / high).
    palette: {
      background: "#eef4e3",
      text: "#31492b",
      accent: "#e2917f",
    },
    decoration: { set: "mixed", density: "high" },
    // Lottie decorations layer OVER the botanicals (both show). Boots with none
    // added; a light instance count and a mostly-palette recolor blend for once
    // the user adds some (each new animation defaults to recolor on).
    lottieAnimations: [],
    lottieDensity: "low",
    lottieRecolorAmount: 0.8,
  },
};
