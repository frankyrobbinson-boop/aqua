/**
 * Theme utilities for the garden title cards:
 *   - Google-fonts loading (the Remotion way, so preview == render)
 *   - fontFamily id → loaded CSS family resolver
 *   - hex color helpers + palette → gradient background builder
 *
 * Fonts are loaded here at module scope via @remotion/google-fonts' `loadFont`,
 * which is `delayRender`-aware: the headless render waits for the font before
 * capturing frames, so the MP4 matches the live <Player> preview. Headless
 * Chromium has no Mac system fonts, which is exactly why we can't lean on one.
 */
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadDMSerifDisplay } from "@remotion/google-fonts/DMSerifDisplay";
import { loadFont as loadFraunces } from "@remotion/google-fonts/Fraunces";
import { loadFont as loadLora } from "@remotion/google-fonts/Lora";
import { loadFont as loadMerriweather } from "@remotion/google-fonts/Merriweather";
import { loadFont as loadNunito } from "@remotion/google-fonts/Nunito";
import { loadFont as loadPlayfairDisplay } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";
import { loadFont as loadQuestrial } from "@remotion/google-fonts/Questrial";
import { loadFont as loadQuicksand } from "@remotion/google-fonts/Quicksand";
import { loadFont as loadWorkSans } from "@remotion/google-fonts/WorkSans";

import type { CardBackground, CardPalette } from "./types";

// Load only the weights the cards use, latin subset — keeps the render fast and
// the download deterministic.
const nunito = loadNunito("normal", {
  weights: ["400", "700", "800"],
  subsets: ["latin"],
});
const fraunces = loadFraunces("normal", {
  weights: ["400", "600", "700"],
  subsets: ["latin"],
});
const quicksand = loadQuicksand("normal", {
  weights: ["400", "500", "700"],
  subsets: ["latin"],
});
const poppins = loadPoppins("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
const workSans = loadWorkSans("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
const lora = loadLora("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
const playfairDisplay = loadPlayfairDisplay("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
// DM Serif Display ships a single weight (400 normal); load just that.
const dmSerifDisplay = loadDMSerifDisplay("normal", {
  weights: ["400"],
  subsets: ["latin"],
});
// Questrial ships a single weight (400 normal); load just that. Signature font
// of the floral card style.
const questrial = loadQuestrial("normal", {
  weights: ["400"],
  subsets: ["latin"],
});
const caveat = loadCaveat("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
const merriweather = loadMerriweather("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});

export const DEFAULT_FONT_ID = "nunito";

const FONT_FAMILY_BY_ID: Record<string, string> = {
  nunito: nunito.fontFamily,
  fraunces: fraunces.fontFamily,
  quicksand: quicksand.fontFamily,
  poppins: poppins.fontFamily,
  worksans: workSans.fontFamily,
  lora: lora.fontFamily,
  playfairdisplay: playfairDisplay.fontFamily,
  dmserifdisplay: dmSerifDisplay.fontFamily,
  questrial: questrial.fontFamily,
  caveat: caveat.fontFamily,
  merriweather: merriweather.fontFamily,
};

/** Resolve a curated font id to its loaded CSS family. Unknown ids (the backend
 *  passes fontFamily through leniently) fall back to the rounded default. */
export function resolveFontFamily(id: string): string {
  return FONT_FAMILY_BY_ID[id] ?? FONT_FAMILY_BY_ID[DEFAULT_FONT_ID];
}

// --- color helpers ---------------------------------------------------------

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** Parse `#rrggbb` → [r,g,b] in 0..255, or null if not a valid 6-digit hex.
 *  Exported so the Lottie recolorer (cards/lottie.ts) reuses the same parse. */
export function hexToRgb(hex: string): [number, number, number] | null {
  if (!HEX_RE.test(hex)) return null;
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) =>
    Math.max(0, Math.min(255, Math.round(n)))
      .toString(16)
      .padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Blend `a` toward `b` by `t` in [0,1]. Falls back to `a` if either is not a
 *  valid `#rrggbb` (the Player can render a hex the user is mid-typing). */
export function mix(a: string, b: string, t: number): string {
  const ra = hexToRgb(a);
  const rb = hexToRgb(b);
  if (!ra || !rb) return a;
  return rgbToHex(
    ra[0] + (rb[0] - ra[0]) * t,
    ra[1] + (rb[1] - ra[1]) * t,
    ra[2] + (rb[2] - ra[2]) * t,
  );
}

export const lighten = (hex: string, amount: number): string =>
  mix(hex, "#ffffff", amount);
export const darken = (hex: string, amount: number): string =>
  mix(hex, "#000000", amount);

/**
 * Build the card fill. `gradient` is a soft vertical garden wash: a lightened
 * top settling into the base background, with a faint accent tint at the
 * bottom. `solid` is just the background color.
 */
export function buildBackground(
  palette: CardPalette,
  background: CardBackground,
): string {
  const base = HEX_RE.test(palette.background) ? palette.background : "#e9f1e4";
  if (background !== "gradient") return base;
  const top = lighten(base, 0.4);
  const bottom = mix(base, palette.accent, 0.22);
  return `linear-gradient(160deg, ${top} 0%, ${base} 55%, ${bottom} 100%)`;
}
