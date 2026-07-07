/**
 * Best-effort Lottie recolor + clone helpers for using a Lottie animation as a
 * card DECORATION (see GardenBloom). Pure + deterministic (no Math.random /
 * Date.now) so the <Player> preview and any still/render stay in lockstep.
 *
 * `recolorLottie` deep-clones the animation and BLENDS its SOLID fill/stroke
 * colors (`ty:"fl"` / `ty:"st"`) toward a target hex by an `amount` (0 = native
 * colors, 1 = full palette), so a downloaded Lottie can pick up the card's
 * palette as strongly or softly as asked. Gradients (`gf`/`gs`) and
 * animated/expression-driven (keyframed) colors are left untouched —
 * best-effort, never throws. Imported by RELATIVE path (no `@/*` alias in the
 * Remotion bundle).
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

/** Recurse the Lottie tree, blending solid fill/stroke colors TOWARD `rgb` by
 *  `amount` (0 = native, 1 = full target) in place on the (already cloned) node.
 *  Only touches STATIC color arrays ([r,g,b(,a)] of numbers); keyframed/
 *  expression colors keep their own `k` shape, so animated fills are left
 *  alone. */
function recolorNode(
  node: unknown,
  rgb: [number, number, number],
  amount: number,
): void {
  if (Array.isArray(node)) {
    for (const child of node) recolorNode(child, rgb, amount);
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
      // Lerp each native RGB channel toward the target by `amount`; preserve any
      // source alpha, recolor only the RGB channels.
      const alpha = typeof k[3] === "number" ? k[3] : 1;
      (color as { k: number[] }).k = [
        k[0] + (rgb[0] - k[0]) * amount,
        k[1] + (rgb[1] - k[1]) * amount,
        k[2] + (rgb[2] - k[2]) * amount,
        alpha,
      ];
    }
  }
  for (const key of Object.keys(obj)) recolorNode(obj[key], rgb, amount);
}

/**
 * Deep-clone `data` and best-effort blend its solid fills/strokes TOWARD
 * `hexColor` by `amount` (0 = native colors, 1 = full palette; clamped, default
 * 1). Never mutates the input; on an invalid hex or any structural surprise it
 * returns the (uncolored) clone rather than throwing — a decoration that isn't
 * recolored beats a crashed card.
 */
export function recolorLottie(
  data: Record<string, unknown>,
  hexColor: string,
  amount = 1,
): Record<string, unknown> {
  const clone = cloneLottie(data);
  const rgb = hexToFloatRgb(hexColor);
  if (!rgb) return clone;
  const a = Math.max(0, Math.min(1, amount));
  try {
    recolorNode(clone, rgb, a);
  } catch {
    // Best-effort: hand back the clone as-is if the tree isn't shaped as
    // expected.
  }
  return clone;
}
