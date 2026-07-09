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

// Shared floral look: Questrial on the locked plum-on-cream palette with a soft
// taupe body (`bodyColor`). Every floral slide's override spreads this, then adds
// its own `variant` + seed `title` (its source-slide heading) + `subtitle`.
const FLORAL_BASE: Partial<CardProps> = {
  fontFamily: "questrial",
  palette: {
    background: "#efe8dc", // cream paper (matches the texture)
    text: "#6b4763", // plum title
    accent: "#9c7f92", // coordinating mauve (FloralCard ignores accent)
  },
  bodyColor: "#7f7268", // soft taupe body
};
// Sample body seeded on the section/overlay floral slides so the overlay
// use-case previews with real copy; the designer clears it for a pure section
// title (the title-only slides 1 + 15 boot with it blank).
const FLORAL_SAMPLE_BODY =
  "A short line of supporting context that reads as body copy.";

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
  // The floral card style — FloralCard + the floral variants table, its own cream
  // paper-texture look (independent of the garden palette). Every slide boots in
  // Questrial on the shared plum-on-cream palette (FLORAL_BASE), keyed to its own
  // layout variant (the `variant` values match the FLORAL_VARIANTS keys) and
  // seeded with its source-slide heading. Title slides (1, 15) are title-only
  // (blank subtitle, per the title-card polish); the section / overlay slides
  // (2–14) seed a sample body for the overlay preview.
  FloralSlide01: { ...FLORAL_BASE, variant: "FloralSlide01", title: "Flora.", subtitle: "" }, // centered title
  FloralSlide02: { ...FLORAL_BASE, variant: "FloralSlide02", title: "Definition of Flora.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide03: { ...FLORAL_BASE, variant: "FloralSlide03", title: "Biological Diversity.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide04: { ...FLORAL_BASE, variant: "FloralSlide04", title: "Ecological Function.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide05: { ...FLORAL_BASE, variant: "FloralSlide05", title: "Endemic Flora.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide06: { ...FLORAL_BASE, variant: "FloralSlide06", title: "Economic Importance.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide07: { ...FLORAL_BASE, variant: "FloralSlide07", title: "Medicinal Flora.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide08: { ...FLORAL_BASE, variant: "FloralSlide08", title: "Flora Conservation.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide09: { ...FLORAL_BASE, variant: "FloralSlide09", title: "Human Impact.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide10: { ...FLORAL_BASE, variant: "FloralSlide10", title: "Flora and Culture.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide11: { ...FLORAL_BASE, variant: "FloralSlide11", title: "Aquatic Flora.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide12: { ...FLORAL_BASE, variant: "FloralSlide12", title: "Flowers and Pollination.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide13: { ...FLORAL_BASE, variant: "FloralSlide13", title: "Flora Adaptation.", subtitle: FLORAL_SAMPLE_BODY }, // heading-right
  FloralSlide14: { ...FLORAL_BASE, variant: "FloralSlide14", title: "Flora Reforestation.", subtitle: FLORAL_SAMPLE_BODY }, // heading-left
  FloralSlide15: { ...FLORAL_BASE, variant: "FloralSlide15", title: "Thanks.", subtitle: "" }, // centered title
};
