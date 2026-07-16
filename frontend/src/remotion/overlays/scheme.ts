/**
 * Overlay color SCHEME resolver — turns the channel palette (plus one flag) into
 * the concrete colors every OST element paints with, so BOTH looks come from the
 * SAME channel tokens (nothing here is a hardcoded gardening color):
 *
 *   default  (invert = false) — cream chip, plum ink (the paper look):
 *     surface = palette.background (cream), ink = palette.text (plum),
 *     hairline = palette.accent (mauve), body = the taupe bodyColor.
 *   inverted (invert = true)  — plum chip, cream ink (the SAME two tokens swapped):
 *     surface = palette.text (plum), ink = palette.background (cream),
 *     body = the cream ink dimmed, hairline = a LIGHT (cream) edge.
 *
 * `surface`/`ink` literally swap WHICH palette token feeds the chip vs the type;
 * only the contrast helpers (hairline / shadow / texture) differ per scheme,
 * because a dark chip and a light chip lift off footage differently — the dark
 * plum chip needs a light edge + a deeper shadow + a quieter paper texture to
 * still read over a bright still (the worst case). All elements — surface, fact
 * text, icon tint, the stamp number + its draw-on underline — read `ink`, so they
 * invert together as one unit.
 *
 * Plain Remotion (consumed only by the bundler): siblings imported by relative
 * path (no `@/*` alias), same as the other overlay parts.
 */
import type { CardPalette } from "../cards/types";
import { OVERLAY_BODY_COLOR } from "./defaults";

export type OverlayScheme = {
  /** Chip paper fill. */
  surface: string;
  /** Primary ink: fact text, hero number, icon tint, underline. */
  ink: string;
  /** Secondary ink: a stamp's leading / trailing phrase. */
  body: string;
  /** Inset hairline ring (8-digit hex incl. alpha) — mauve on cream, a light
   *  cream edge on plum so the dark chip separates from footage. */
  hairline: string;
  /** Chip drop shadow — deeper/wider for the dark chip so it still lifts off. */
  shadow: string;
  /** Paper-texture opacity over the surface — lower on plum so the dark surface
   *  keeps its color (the cream texture would otherwise wash it out). */
  textureOpacity: number;
};

/** Resolve the two OST looks from ONE channel palette. `invert` picks which token
 *  feeds surface vs ink; `bodyColor` (the channel's taupe) is the default scheme's
 *  secondary ink — the inverted scheme derives its own from the cream token. */
export function resolveOverlayScheme(
  palette: CardPalette,
  invert: boolean,
  bodyColor?: string,
): OverlayScheme {
  if (invert) {
    return {
      surface: palette.text, // plum
      ink: palette.background, // cream
      body: `${palette.background}b3`, // cream @ ~70% — the softer trailing phrase
      hairline: `${palette.background}59`, // ~35% cream edge lifts the dark chip
      shadow: "0 16px 40px rgba(0, 0, 0, 0.46)", // deeper: a dark chip needs more lift
      textureOpacity: 0.16, // quiet, so the plum stays plum
    };
  }
  return {
    surface: palette.background, // cream
    ink: palette.text, // plum
    body: bodyColor ?? OVERLAY_BODY_COLOR, // taupe
    hairline: `${palette.accent}66`, // ~40% mauve hairline
    shadow: "0 12px 34px rgba(0, 0, 0, 0.30)",
    textureOpacity: 0.55,
  };
}
