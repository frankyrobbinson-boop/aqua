/**
 * Gardening-channel token SEED for the OST overlays — the cream / Questrial /
 * plum floral look, mirrored from the floral cards' FLORAL_BASE
 * (cards/defaults.ts). Shared by Root.tsx's Composition defaultProps and the
 * design-render script (scripts/render-ost-overlays.mjs) so preview and render
 * start in lockstep. A DIFFERENT channel supplies different tokens; nothing here
 * is hardcoded INSIDE the components — they read palette / fontFamily /
 * bodyColor / icon from props.
 */
import type { CardPalette } from "../cards/types";
import type { OverlayProps } from "./types";

/** Cream paper / plum ink / mauve hairline — the same palette the floral cards
 *  boot on (cards/defaults.ts FLORAL_BASE). */
export const OVERLAY_PALETTE: CardPalette = {
  background: "#efe8dc", // cream paper (matches the texture)
  text: "#6b4763", // plum ink
  accent: "#9c7f92", // coordinating mauve (chip hairline)
};

/** Soft taupe — the unit / trailing phrase of a measurement stamp. */
export const OVERLAY_BODY_COLOR = "#7f7268";

/** Boot props for the FloralTag comp (a plain fact). `invert: false` is the
 *  channel's default OST look (cream chip + plum ink); flip it for the plum-chip
 *  scheme (both derive from OVERLAY_PALETTE — see scheme.ts). `calendar-dots` is
 *  the clean calendar (no "12"). */
export const FLORAL_TAG_DEFAULTS: OverlayProps = {
  fact: "Divide every 2-3 years",
  palette: OVERLAY_PALETTE,
  fontFamily: "questrial",
  bodyColor: OVERLAY_BODY_COLOR,
  icon: "calendar-dots",
  invert: false,
  position: "top-left",
  durationInSeconds: 3.65,
};

/** Boot props for the MeasurementStamp comp (a number-hero fact). `invert: false`
 *  is the channel default (cream chip + plum ink); flip for the plum scheme. */
export const MEASUREMENT_STAMP_DEFAULTS: OverlayProps = {
  fact: "Plant 2 inches deep",
  palette: OVERLAY_PALETTE,
  fontFamily: "questrial",
  bodyColor: OVERLAY_BODY_COLOR,
  icon: "ruler",
  invert: false,
  position: "top-left",
  durationInSeconds: 3.65,
};
