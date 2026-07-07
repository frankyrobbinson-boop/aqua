/**
 * Best-effort Lottie recolor + clone helpers for using a Lottie animation as a
 * card DECORATION (see GardenBloom). Pure + deterministic (no Math.random /
 * Date.now) so the <Player> preview and any still/render stay in lockstep.
 *
 * `recolorLottie` deep-clones the animation and overrides SOLID fill/stroke
 * colors (`ty:"fl"` / `ty:"st"`) to a target hex, so a downloaded Lottie picks
 * up the card's palette. Gradients (`gf`/`gs`) and animated/expression-driven
 * (keyframed) colors are left untouched — best-effort, never throws. Imported
 * by RELATIVE path (no `@/*` alias in the Remotion bundle).
 */
import { hexToRgb } from "./theme";

/** Structural clone of pure-JSON Lottie data (no functions / cycles), so each
 *  <Lottie> instance owns its object: lottie-web annotates animationData in
 *  place, so sharing one reference across simultaneous instances can glitch. */
export function cloneLottie(
  data: Record<string, unknown>,
): Record<string, unknown> {
  return JSON.parse(JSON.stringify(data)) as Record<string, unknown>;
}

/** True if `data` looks like a Lottie document (an object with a `layers`
 *  array). Guards the card against a malformed file being treated as one. */
export function isLikelyLottie(
  data: unknown,
): data is Record<string, unknown> {
  return (
    !!data &&
    typeof data === "object" &&
    Array.isArray((data as { layers?: unknown }).layers)
  );
}

/** `#rrggbb` → [r,g,b] in 0..1 (Lottie's color space), or null if invalid. */
function hexToFloatRgb(hex: string): [number, number, number] | null {
  const rgb = hexToRgb(hex);
  if (!rgb) return null;
  return [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255];
}

/** Recurse the Lottie tree, overriding solid fill/stroke colors in place on the
 *  (already cloned) node. Only touches STATIC color arrays ([r,g,b(,a)] of
 *  numbers); keyframed/expression colors keep their own `k` shape, so animated
 *  fills are left alone. */
function recolorNode(node: unknown, rgb: [number, number, number]): void {
  if (Array.isArray(node)) {
    for (const child of node) recolorNode(child, rgb);
    return;
  }
  if (!node || typeof node !== "object") return;
  const obj = node as Record<string, unknown>;
  if (obj.ty === "fl" || obj.ty === "st") {
    const color = obj.c as { k?: unknown } | undefined;
    const k = color?.k;
    if (
      Array.isArray(k) &&
      k.length >= 3 &&
      k.every((n) => typeof n === "number")
    ) {
      // Preserve any source alpha; recolor only the RGB channels.
      const alpha = typeof k[3] === "number" ? k[3] : 1;
      (color as { k: number[] }).k = [rgb[0], rgb[1], rgb[2], alpha];
    }
  }
  for (const key of Object.keys(obj)) recolorNode(obj[key], rgb);
}

/**
 * Deep-clone `data` and best-effort recolor its solid fills/strokes to
 * `hexColor`. Never mutates the input; on an invalid hex or any structural
 * surprise it returns the (uncolored) clone rather than throwing — a decoration
 * that isn't recolored beats a crashed card.
 */
export function recolorLottie(
  data: Record<string, unknown>,
  hexColor: string,
): Record<string, unknown> {
  const clone = cloneLottie(data);
  const rgb = hexToFloatRgb(hexColor);
  if (!rgb) return clone;
  try {
    recolorNode(clone, rgb);
  } catch {
    // Best-effort: hand back the clone as-is if the tree isn't shaped as
    // expected.
  }
  return clone;
}
