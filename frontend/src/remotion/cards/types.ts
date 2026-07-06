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

export type CardPalette = {
  background: string;
  text: string;
  accent: string;
};

export type CardDecoration = {
  set: DecorationSet;
  density: DecorationDensity;
};

export type CardProps = {
  title: string;
  subtitle?: string;
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
};
