/**
 * PhosphorIcon — renders a Phosphor icon BY NAME, tinted to a single channel
 * color. The icon is a swappable prop: pass `name="ruler"` and it resolves to
 * the committed SVG public/icons/phosphor/regular/<name>.svg (via staticFile),
 * then paints it through a CSS mask so ANY monochrome Phosphor glyph takes the
 * tint — here the channel plum (palette.text). The mask uses the SVG's own
 * alpha, so the same code tints every icon in the set with no per-icon work and
 * no new dependency.
 *
 * (The alternative is the @phosphor-icons/react component — not installed. The
 * mask-by-name path keeps this look-dev pass dependency-free and lets a future
 * fact→icon resolver simply hand us a name string.)
 *
 * Plain Remotion (consumed only by the bundler): siblings imported by relative
 * path (no `@/*` alias), same as the other overlay parts.
 */
import type { CSSProperties } from "react";
import { staticFile } from "remotion";

/** Weight subfolder under public/icons/phosphor. Regular is the floral look —
 *  a channel could point at a different weight later. */
const ICON_DIR = "icons/phosphor/regular/";

export function PhosphorIcon({
  name,
  color,
  size = 56,
  style,
}: {
  /** Phosphor icon name, e.g. "ruler" / "sun" / "calendar". */
  name: string;
  /** Tint (channel token — the overlays pass palette.text, the plum ink). */
  color: string;
  /** Rendered box size in px (the glyph is centered + contained). */
  size?: number;
  style?: CSSProperties;
}) {
  const url = staticFile(ICON_DIR + name + ".svg");
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        // The tint shows only through the glyph's alpha (the mask below).
        backgroundColor: color,
        WebkitMaskImage: `url(${url})`,
        maskImage: `url(${url})`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        ...style,
      }}
    />
  );
}
