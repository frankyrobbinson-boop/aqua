/**
 * LottiePreview — a bare evaluation stage for a single Lottie animation. Centers
 * the animation on a soft garden wash so the curation tab can loop and compare
 * downloaded Lotties. This is NOT a title card: no text, no palette props — just
 * the animation contained within the frame. Rendering Lotties INTO the cards is
 * a later step.
 *
 * A plain Remotion component (no "use client" directive, like the cards): it is
 * consumed by the browser <Player> in LottieLibrary AND registered as a
 * <Composition> in Root.tsx for the Node renderer. Siblings/deps are imported
 * the same way the cards do so both bundlers resolve it.
 */
import { Lottie, type LottieAnimationData } from "@remotion/lottie";
import { AbsoluteFill } from "remotion";

/** Pale sage — a neutral garden backdrop that flatters botanical Lotties. */
const DEFAULT_BG = "#e7efe3";

export type LottiePreviewProps = {
  /** Parsed Lottie JSON, or null to show just the backdrop. */
  animationData: Record<string, unknown> | null;
  bg?: string;
};

export const LottiePreview = ({
  animationData,
  bg = DEFAULT_BG,
}: LottiePreviewProps) => {
  return (
    <AbsoluteFill
      style={{
        background: bg,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      {animationData ? (
        <Lottie
          // The validated Lottie JSON is a superset of LottieAnimationData; the
          // prop is typed loosely (Record) so callers needn't assert the shape.
          animationData={animationData as unknown as LottieAnimationData}
          loop
          style={{ width: "70%", height: "70%" }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
