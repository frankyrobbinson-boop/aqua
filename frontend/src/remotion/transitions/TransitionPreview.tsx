/**
 * TransitionPreview — the looping two-clip stage the /remotion "Transitions" tab
 * drives via the <Player>. Sample A plays, the chosen transition runs, Sample B
 * plays: a TransitionSeries of two Sequences bridged by one
 * TransitionSeries.Transition whose presentation + timing come from the registry
 * (registry.build). Dimensions / fps come from useVideoConfig so the same values
 * feed presentations that need them (e.g. clockWipe).
 *
 * Each Sequence's length is DERIVED from the transition duration
 * (transitionFrames + hold), so a Sequence is ALWAYS strictly longer than the
 * Transition it feeds — Remotion rejects a Sequence shorter than the next
 * Transition, which used to break long-duration previews.
 *
 * Preview-only: registered as a Composition in Root.tsx but NOT in ALLOWED_COMPS
 * (backend). The /remotion "Transitions" tab renders it via the live <Player>
 * for Tier-A transitions and via a short MP4 render (POST /transitions/preview)
 * for the Tier-B WebGL shaders the browser can't run. Never part of the pipeline.
 *
 * Plain Remotion (no "use client"): consumed by the browser <Player> AND the
 * Remotion bundler (Root.tsx). Siblings imported by relative path so both
 * bundlers resolve the tree.
 */
import { TransitionSeries } from "@remotion/transitions";
import { useVideoConfig } from "remotion";

import { getTransition, type TransitionParams } from "./registry";
import { SampleClip } from "./SampleClip";

/** Default on-screen hold (frames) on each sample clip's NON-overlapping side.
 *  A clip's length is the transition duration + this hold, so a Sequence is
 *  always strictly longer than the Transition it feeds. The render-preview
 *  endpoint passes a smaller hold to keep the rendered MP4 short. */
export const HOLD_FRAMES = 30;

/** Effective transition length in frames — matches registry buildTiming's clamp
 *  so the sequence/transition math and the actual transition timing agree. */
function transitionFramesOf(params: TransitionParams): number {
  return Math.max(1, Math.round(params.durationInFrames));
}

/** Total length of the two-clip preview stage: two `transitionFrames + hold`
 *  Sequences overlapped by the transition, i.e. `transitionFrames + 2*hold`.
 *  The designer feeds this to the <Player>; Root.tsx feeds it to the preview
 *  Composition's calculateMetadata so a render matches the on-screen length. */
export function previewDurationInFrames(
  params: TransitionParams,
  holdFrames: number = HOLD_FRAMES,
): number {
  const hold = Math.max(1, Math.round(holdFrames));
  return transitionFramesOf(params) + 2 * hold;
}

export type TransitionPreviewProps = {
  type: string;
  params: TransitionParams;
  /** On-screen hold (frames) per clip; see HOLD_FRAMES. Optional — defaults to
   *  HOLD_FRAMES; the render-preview endpoint passes a smaller value so the
   *  rendered clip stays short. */
  holdFrames?: number;
  /** Optional real stills — forwarded to the sample clips so the same preview
   *  can later run over pipeline frames without touching transition code. */
  sampleA?: string;
  sampleB?: string;
};

export const TransitionPreview = ({
  type,
  params,
  holdFrames,
  sampleA,
  sampleB,
}: TransitionPreviewProps) => {
  const { width, height, fps } = useVideoConfig();
  const { presentation, timing } = getTransition(type).build({
    params,
    width,
    height,
    fps,
  });

  // Each clip runs for the transition duration + a brief hold, so a Sequence is
  // always longer than the Transition it feeds. The two clips overlap by the
  // transition duration.
  const hold = Math.max(1, Math.round(holdFrames ?? HOLD_FRAMES));
  const seqFrames = transitionFramesOf(params) + hold;

  return (
    <TransitionSeries>
      <TransitionSeries.Sequence durationInFrames={seqFrames}>
        <SampleClip variant="a" imageUrl={sampleA} />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={presentation} timing={timing} />
      <TransitionSeries.Sequence durationInFrames={seqFrames}>
        <SampleClip variant="b" imageUrl={sampleB} />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
