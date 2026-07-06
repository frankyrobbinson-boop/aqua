/**
 * Title-card entrance animations — the centerpiece of the /remotion designer.
 *
 * Every entrance is driven by `interpolate` + `Easing` over a shared intro
 * window (~0.9s, converted to frames from the composition fps), with
 * extrapolation clamped on both ends so the value holds steady once the intro
 * completes. We deliberately avoid `spring()`: its settle reads techy, and the
 * frame-based interpolate keeps preview == render perfectly deterministic.
 *
 * Cards call `useTextEntrance` ONCE and spread the returned `style` on the
 * title element, rendering the returned `text` (identical to the input except
 * for the typewriter, which reveals characters over time).
 */
import { useMemo } from "react";
import type { CSSProperties } from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export type AnimationId =
  | "rise"
  | "fade"
  | "scale"
  | "slide"
  | "typewriter"
  | "none";

/** id + label pairs for the animation `<select>`. */
export const ANIMATION_OPTIONS: ReadonlyArray<{ id: AnimationId; label: string }> = [
  { id: "rise", label: "Rise" },
  { id: "fade", label: "Fade" },
  { id: "scale", label: "Scale" },
  { id: "slide", label: "Slide" },
  { id: "typewriter", label: "Typewriter" },
  { id: "none", label: "None" },
];

const KNOWN: ReadonlySet<string> = new Set(ANIMATION_OPTIONS.map((o) => o.id));

// Shared intro length in seconds. Converted to frames per-composition so the
// timing is identical across preview and render regardless of fps.
const INTRO_SECONDS = 0.9;
// Typewriter reveal speed. The window scales with text length so long titles
// still finish typing in a sensible time.
const TYPEWRITER_CPS = 24;

const clampEase = (easing: (n: number) => number) => ({
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
  easing,
});

/**
 * Returns the animated `style` for the title plus the `text` to render. Unknown
 * animation ids (the backend passes style enums through leniently) fall back to
 * the default `rise`.
 */
export function useTextEntrance(
  animation: string,
  text: string,
): { style: CSSProperties; text: string } {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const id: AnimationId = KNOWN.has(animation)
    ? (animation as AnimationId)
    : "rise";

  const intro = Math.max(1, Math.round(INTRO_SECONDS * fps));

  return useMemo(() => {
    switch (id) {
      case "none":
        return { style: { opacity: 1 }, text };

      case "fade": {
        const opacity = interpolate(
          frame,
          [0, intro],
          [0, 1],
          clampEase(Easing.out(Easing.ease)),
        );
        return { style: { opacity }, text };
      }

      case "scale": {
        const opacity = interpolate(
          frame,
          [0, intro],
          [0, 1],
          clampEase(Easing.out(Easing.cubic)),
        );
        const scale = interpolate(
          frame,
          [0, intro],
          [0.92, 1],
          clampEase(Easing.out(Easing.cubic)),
        );
        return { style: { opacity, transform: `scale(${scale})` }, text };
      }

      case "slide": {
        const opacity = interpolate(
          frame,
          [0, intro],
          [0, 1],
          clampEase(Easing.out(Easing.cubic)),
        );
        const x = interpolate(
          frame,
          [0, intro],
          [-60, 0],
          clampEase(Easing.out(Easing.cubic)),
        );
        return { style: { opacity, transform: `translateX(${x}px)` }, text };
      }

      case "typewriter": {
        const chars = Math.max(1, text.length);
        const end = Math.max(1, Math.round((chars / TYPEWRITER_CPS) * fps));
        const visible = Math.floor(
          interpolate(frame, [0, end], [0, chars], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        );
        return { style: { opacity: 1 }, text: text.slice(0, visible) };
      }

      case "rise":
      default: {
        const opacity = interpolate(
          frame,
          [0, intro],
          [0, 1],
          clampEase(Easing.out(Easing.cubic)),
        );
        const y = interpolate(
          frame,
          [0, intro],
          [40, 0],
          clampEase(Easing.out(Easing.cubic)),
        );
        return { style: { opacity, transform: `translateY(${y}px)` }, text };
      }
    }
  }, [id, frame, intro, fps, text]);
}

/**
 * Small shared helper for secondary elements (subtitles, accents, bands): a
 * gentle fade-in starting `delaySeconds` in, over `durationSeconds`. Frame
 * based, so it matches between preview and render.
 */
export function useFadeIn(delaySeconds = 0, durationSeconds = 0.7): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = Math.round(delaySeconds * fps);
  const end = start + Math.max(1, Math.round(durationSeconds * fps));
  return interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.ease),
  });
}
