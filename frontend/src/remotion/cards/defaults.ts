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
  { id: "poppins", label: "Poppins · geometric" },
  { id: "worksans", label: "Work Sans · clean sans" },
  { id: "questrial", label: "Questrial · airy sans" },
  { id: "lora", label: "Lora · warm serif" },
  { id: "playfairdisplay", label: "Playfair Display · elegant serif" },
  { id: "dmserifdisplay", label: "DM Serif Display · bold serif" },
  { id: "caveat", label: "Caveat · handwritten" },
  { id: "merriweather", label: "Merriweather · essayistic serif" },
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
  // The two section-header cards boot as a recognizable numbered section header
  // (badge above a short label) so the designer opens looking like real output.
  // Palette/decoration stay inherited from CARD_DEFAULTS.
  GardenFramed: {
    index: "1",
    title: "Hydrangeas",
    subtitle: "Big blooms, all summer",
  },
  GardenBand: {
    index: "1",
    title: "Hydrangeas",
    subtitle: "Big blooms, all summer",
  },
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
    // floral rose accent — foliage greens derive from `foliageColor` (its own
    // leaf color, defaulting to the same deep green), blooms + the highlight word
    // from the accent. Boots lush (mixed / high).
    palette: {
      background: "#eef4e3",
      text: "#31492b",
      accent: "#e2917f",
    },
    // SVG foliage/leaf green — INDEPENDENT of palette.text (which now only colors
    // the title/subtitle). Set to the SAME deep green as the text so the default
    // render is pixel-identical; change it to recolor the leaves alone.
    foliageColor: "#31492b",
    decoration: { set: "mixed", density: "high" },
    // Lottie decorations layer OVER the botanicals (both show). Boots with none
    // added; a light instance count and a mostly-palette recolor blend for once
    // the user adds some (each new animation defaults to recolor on).
    lottieAnimations: [],
    lottieDensity: "low",
    lottieRecolorAmount: 0.8,
    // Lottie recolor target — SEPARATE from palette.accent (which still colors
    // the highlight word + the SVG blooms). Defaults to the SAME accent rose so
    // the look is unchanged until the user picks a new color.
    lottieRecolorColor: "#e2917f",
  },
  // The floral card style — FloralCard + the floral variants table, its own
  // cream paper-texture look (independent of the garden palette). Both slides
  // boot in Questrial on the same plum-on-cream palette with a soft-taupe body
  // (`bodyColor`); each keys into its own layout variant (see cards/floral/
  // variants.ts — the `variant` values match the FLORAL_VARIANTS keys).
  FloralSlide01: {
    // Slide 1 — "Flora." centered hero, botanicals framing the border.
    variant: "FloralSlide01",
    fontFamily: "questrial",
    title: "Flora.",
    palette: {
      background: "#efe8dc", // cream paper (matches the texture)
      text: "#6b4763", // plum title
      accent: "#9c7f92", // coordinating mauve (FloralCard ignores accent)
    },
    bodyColor: "#7f7268", // soft taupe body
  },
  FloralSlide02: {
    // Slide 2 — numbered section header, heading anchored left with the
    // botanicals massed down the right. No body (a clean section title).
    variant: "FloralSlide02",
    fontFamily: "questrial",
    title: "Number 1: Bee balm",
    subtitle: "",
    palette: {
      background: "#efe8dc",
      text: "#6b4763",
      accent: "#9c7f92",
    },
    bodyColor: "#7f7268",
  },
};
