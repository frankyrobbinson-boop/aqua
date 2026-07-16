/**
 * On-screen-text (OST) overlay prop shape — the small fact chips that animate
 * OVER real footage (NOT the full-screen title/section cards). Two components
 * consume it: FloralTag (a plain fact on a cream-paper chip) and
 * MeasurementStamp (a number-hero fact with a drawn-on underline).
 *
 * Like the floral CARDS, an overlay reads its LOOK from channel tokens passed as
 * props — `palette` (paper / plum / accent), `fontFamily`, `bodyColor` — plus the
 * shared paper texture and a Phosphor `icon` accent (tinted the channel plum).
 * Swap those tokens and a different channel restyles the same component; nothing
 * here is hardcoded to gardening. Declared as a `type` (not interface) so Remotion's
 * Composition/Player generics (which constrain props to Record<string, unknown>)
 * accept it, same as CardProps.
 */
import type { CardPalette } from "../cards/types";

/** Where the chip anchors. Deliberately upper-third / side only — there is NO
 *  bottom option, so an OST chip can never collide with the subtitle band. */
export type OverlayPosition =
  | "top-left"
  | "top-right"
  | "top-center"
  | "left"
  | "right";

export type OverlayProps = {
  /** The fact to display (e.g. "6 hours of sun", "Plant 2 inches deep"). */
  fact: string;
  /** Channel palette feeding BOTH schemes (see `invert` + scheme.ts). Default
   *  scheme: `background` = the cream paper chip, `text` = the plum ink
   *  (fact / number / underline); inverted, the SAME two tokens swap (plum chip,
   *  cream ink). `accent` = the mauve chip hairline (default scheme only). */
  palette: CardPalette;
  /** One of the curated font ids (see FONT_OPTIONS) — the floral channel supplies
   *  Questrial as its display/body face. */
  fontFamily: string;
  /** Secondary ink (soft taupe) for the unit / trailing phrase of a stamp.
   *  Optional; defaults to the floral taupe (see defaults.ts). */
  bodyColor?: string;
  /** Phosphor icon NAME (e.g. "ruler", "sun", "calendar") rendered as the focal
   *  accent, tinted the channel plum (palette.text) — it REPLACES the old corner
   *  sprig. Swap the name to swap the icon; PhosphorIcon resolves it to a
   *  staticFile SVG. Optional; absent = no icon. */
  icon?: string;
  /** Channel-scoped color scheme for the chip. `false` (default) = cream chip +
   *  plum ink; `true` = the tokens INVERTED (plum chip + cream ink). Both derive
   *  from the SAME `palette` (see scheme.ts) — nothing is hardcoded. Applies to
   *  both overlays; every element (surface, text, icon, number, underline)
   *  inverts together. */
  invert?: boolean;
  /** Chip anchor (never the bottom band). Defaults to "top-left". */
  position?: OverlayPosition;
  /** Clamp drives durationInFrames via calculateMetadata; the exit auto-anchors
   *  to the clip END, so a longer clip simply holds longer. */
  durationInSeconds: number;
  /** DESIGN-RENDER ONLY: a public/ path (resolved via staticFile) drawn
   *  full-bleed BEHIND the overlay so the look can be judged over real footage.
   *  Absent in real overlay use — the chip is then transparent-backed for
   *  compositing. NOT a pipeline field (this module is look-dev only). */
  backgroundSrc?: string;
};
