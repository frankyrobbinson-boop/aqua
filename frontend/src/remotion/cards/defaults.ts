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
