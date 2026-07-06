/**
 * Card canvas: paints the solid/gradient fill and hosts a decoration slot
 * behind the content. Each card supplies its own `decoration` node (scattered
 * layer, corner vines, or a lower band) so the fill and the botanicals stay
 * independent — a card can show a gradient AND decorations at once.
 */
import type { ReactNode } from "react";
import { AbsoluteFill } from "remotion";

import { buildBackground } from "./theme";
import type { CardBackground, CardPalette } from "./types";

export function Background({
  palette,
  background,
  decoration,
  children,
}: {
  palette: CardPalette;
  background: CardBackground;
  /** Rendered behind `children`. */
  decoration?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <AbsoluteFill
      style={{ background: buildBackground(palette, background), overflow: "hidden" }}
    >
      {decoration}
      {children}
    </AbsoluteFill>
  );
}
