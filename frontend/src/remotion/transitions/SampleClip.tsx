/**
 * SampleClip — procedural, richly-decorated garden panel used ONLY as stand-in
 * content for the transitions preview (never rendered to MP4, never in the
 * pipeline). Two clearly distinct variants — "a" (warm) and "b" (cool) — each a
 * gradient garden wash (theme.buildBackground) layered with a couple of
 * botanical SVGs (cards/decorations) and a big letter, so dissolves / wipes /
 * flicks are legible frame-to-frame. Pass `imageUrl` to swap in a real still
 * later without touching any transition code.
 *
 * Plain Remotion (no "use client", no hooks): consumed by the <Player> inside
 * TransitionPreview and, transitively, the preview Composition. Siblings
 * imported by relative path so both bundlers resolve the tree.
 */
import { AbsoluteFill } from "remotion";

import { BerrySprig, BroadLeaf, Flower, Sprig } from "../cards/decorations";
import { buildBackground } from "../cards/theme";
import type { CardPalette } from "../cards/types";

export type SampleVariant = "a" | "b";

export type SampleClipProps = {
  variant: SampleVariant;
  /** Optional real still — when set, replaces the procedural panel (cover-fit)
   *  so the same transition preview can later run over pipeline frames. */
  imageUrl?: string;
};

// Warm vs cool palettes + different botanicals so A and B stay distinct through
// a dissolve or a slow wipe.
const PALETTE_A: CardPalette = {
  background: "#f4e3c8",
  text: "#8a4326",
  accent: "#e08a52",
};
const PALETTE_B: CardPalette = {
  background: "#d6e9df",
  text: "#1f4a44",
  accent: "#4fa39c",
};

export const SampleClip = ({ variant, imageUrl }: SampleClipProps) => {
  if (imageUrl) {
    return (
      <AbsoluteFill
        style={{
          backgroundImage: `url(${imageUrl})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
    );
  }

  const isA = variant === "a";
  const palette = isA ? PALETTE_A : PALETTE_B;

  return (
    <AbsoluteFill
      style={{
        background: buildBackground(palette, "gradient"),
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      {/* Two botanicals per variant — different shapes + corners so the two
          scenes read as distinct through a transition. */}
      {isA ? (
        <>
          <div style={{ position: "absolute", left: "7%", top: "12%" }}>
            <Flower palette={palette} size={280} />
          </div>
          <div style={{ position: "absolute", right: "8%", bottom: "10%" }}>
            <Sprig palette={palette} size={300} />
          </div>
        </>
      ) : (
        <>
          <div style={{ position: "absolute", right: "7%", top: "12%" }}>
            <BroadLeaf palette={palette} size={300} />
          </div>
          <div style={{ position: "absolute", left: "8%", bottom: "9%" }}>
            <BerrySprig palette={palette} size={300} />
          </div>
        </>
      )}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 12,
          color: palette.text,
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <span style={{ fontSize: 420, fontWeight: 800, lineHeight: 1 }}>
          {isA ? "A" : "B"}
        </span>
        <span
          style={{
            fontSize: 56,
            fontWeight: 600,
            letterSpacing: 2,
            opacity: 0.75,
            textTransform: "uppercase",
          }}
        >
          {isA ? "Scene A" : "Scene B"}
        </span>
      </div>
    </AbsoluteFill>
  );
};
