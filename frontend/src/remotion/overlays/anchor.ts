/**
 * Chip anchoring for the OST overlays. Maps an OverlayPosition to the flex
 * alignment + safe-margin padding of the full-frame container the chip sits in.
 * Every option lives in the upper third or along a side — there is deliberately
 * NO bottom option, so an OST chip can never collide with the subtitle band.
 */
import type { CSSProperties } from "react";

import type { OverlayPosition } from "./types";

// Safe margins from the frame edge (px on the 1920x1080 canvas).
const SIDE_MARGIN = 120;
const TOP_MARGIN = 96;

/** Full-frame flex container style that pins the chip to `position`. */
export function anchorFillStyle(position: OverlayPosition): CSSProperties {
  const base: CSSProperties = {
    display: "flex",
    // AbsoluteFill defaults to flexDirection: "column"; force "row" so
    // justifyContent is the HORIZONTAL axis and alignItems the VERTICAL one,
    // matching every case below (otherwise the axes swap and e.g. top-center
    // renders center-left).
    flexDirection: "row",
    padding: `${TOP_MARGIN}px ${SIDE_MARGIN}px`,
  };
  switch (position) {
    case "top-right":
      return { ...base, justifyContent: "flex-end", alignItems: "flex-start" };
    case "top-center":
      return { ...base, justifyContent: "center", alignItems: "flex-start" };
    case "left":
      return { ...base, justifyContent: "flex-start", alignItems: "center" };
    case "right":
      return { ...base, justifyContent: "flex-end", alignItems: "center" };
    case "top-left":
    default:
      return { ...base, justifyContent: "flex-start", alignItems: "flex-start" };
  }
}
