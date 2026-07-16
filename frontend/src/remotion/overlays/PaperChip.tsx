/**
 * PaperChip — the shared PAPER surface both OST overlays sit on: the channel
 * paper texture over the scheme's surface color, a soft drop shadow, and a mauve
 * (or, inverted, a light) hairline. This surface IS the legibility guarantee — it
 * lifts the ink off ANY footage, including a bright background (the worst case).
 *
 * One treatment: the boxy "chip" — a tight radius + a hairline ring (the earlier
 * edge-less "plate" was dropped; the chip is the look). Its colors come from the
 * resolved OverlayScheme (see scheme.ts), so the SAME component renders both the
 * cream-chip and the inverted plum-chip look — on plum the hairline flips to a
 * LIGHT edge, the shadow deepens, and the texture backs off so the dark chip
 * still lifts off footage. The icon is composed BY THE OVERLAY as a child, so
 * PaperChip is purely the surface.
 *
 * Plain Remotion (consumed only by the bundler): siblings imported by relative
 * path (no `@/*` alias).
 */
import type { CSSProperties, ReactNode } from "react";
import { Img, staticFile } from "remotion";

import type { OverlayScheme } from "./scheme";

// Shared floral-style asset — identical to FloralCard's (public/cardstyle/…).
const TEXTURE_SRC = "cardstyle/texture.jpg";

// Chip surface geometry (fixed now that the "plate" treatment is gone).
const RADIUS = 20;
const PADDING = "28px 46px";

export function PaperChip({
  scheme,
  style,
  children,
}: {
  scheme: OverlayScheme;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        position: "relative",
        // surface color (a channel token via the scheme) behind the texture
        backgroundColor: scheme.surface,
        borderRadius: RADIUS,
        boxShadow: scheme.shadow,
        padding: PADDING,
        ...style,
      }}
    >
      {/* Paper texture, clipped to the rounded surface in its OWN overflow-hidden
          layer; the hairline rides the texture edge as an inset ring. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: RADIUS,
          overflow: "hidden",
          boxShadow: `inset 0 0 0 1.5px ${scheme.hairline}`,
        }}
      >
        <Img
          src={staticFile(TEXTURE_SRC)}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            opacity: scheme.textureOpacity,
          }}
        />
      </div>

      {/* Content sits above the texture. */}
      <div style={{ position: "relative" }}>{children}</div>
    </div>
  );
}
