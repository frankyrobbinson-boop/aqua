/**
 * Shared OST overlay motion grammar — matches the cards/camera (ease-out cubic,
 * NO spring; a frame-based `interpolate` so preview == render). Three phases:
 *   entrance — slide UP ~8px + fade in over ~0.4s,
 *   hold     — dead still (for as long as the clip runs),
 *   exit     — fade out over ~0.25s (faster than the entrance), AUTO-ANCHORED to
 *              the clip END so a longer clip just holds longer.
 * A second hook, `useDrawOn`, animates a left→right "draw on" (0→1) over ~0.3s
 * after a delay — the MeasurementStamp's underline.
 *
 * Deliberately NOT `spring()` (its settle reads techy) and NOT reused from
 * cards/animations.ts: those entrances hold forever, whereas an OST chip also
 * EXITS. Same easing family as the cards, though (Easing.out(Easing.cubic)).
 */
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Phase lengths in seconds — the shared grammar (see the module header).
export const ENTER_SECONDS = 0.4;
export const EXIT_SECONDS = 0.25;
export const DRAW_ON_SECONDS = 0.3;

// Ease-out for the entrance + draw-on (settles and holds); a gentle ease-in for
// the exit so the fade accelerates away.
const EASE_OUT = Easing.out(Easing.cubic);
const EASE_IN = Easing.in(Easing.cubic);

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export type OverlayLifecycle = {
  opacity: number;
  translateY: number;
  /** Frames the entrance spans — a caller delays secondary motion (e.g. the
   *  underline) until the chip has landed. */
  enterFrames: number;
};

/** Entrance (slide up 8px + fade over ENTER_SECONDS) → hold → exit (fade over
 *  EXIT_SECONDS, anchored to the clip end). Returns the animated opacity +
 *  translateY (px) to spread on the chip wrapper, plus `enterFrames`. */
export function useOverlayLifecycle(): OverlayLifecycle {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const enter = Math.max(1, Math.round(ENTER_SECONDS * fps));
  const exit = Math.max(1, Math.round(EXIT_SECONDS * fps));

  const opacityIn = interpolate(frame, [0, enter], [0, 1], {
    easing: EASE_OUT,
    ...clamp,
  });
  // Starts 8px LOW and rises to 0 — a slide UP into place.
  const translateY = interpolate(frame, [0, enter], [8, 0], {
    easing: EASE_OUT,
    ...clamp,
  });
  const opacityOut = interpolate(
    frame,
    [durationInFrames - exit, durationInFrames],
    [1, 0],
    { easing: EASE_IN, ...clamp },
  );

  return { opacity: opacityIn * opacityOut, translateY, enterFrames: enter };
}

/** A left→right "draw on" progress 0→1 over DRAW_ON_SECONDS, starting
 *  `delayFrames` in (drives the MeasurementStamp underline's scaleX). */
export function useDrawOn(delayFrames: number): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = Math.max(0, Math.round(delayFrames));
  const end = start + Math.max(1, Math.round(DRAW_ON_SECONDS * fps));
  return interpolate(frame, [start, end], [0, 1], { easing: EASE_OUT, ...clamp });
}
