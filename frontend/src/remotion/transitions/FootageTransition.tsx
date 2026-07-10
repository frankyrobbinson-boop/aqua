/**
 * FootageTransition — a footage-to-footage transition stage: clip A holds, a
 * chosen studio transition runs (EASED), then clip B holds. Unlike
 * TransitionPreview (procedural SampleClips, studio linear/spring timing), this
 * plays two REAL <OffthreadVideo> clips and drives the transition with an EASED
 * `linearTiming` (ease-in-out cubic by default) — the whole point: a crossfade's
 * easing is barely perceptible, but easing carries real significance on MOTION
 * transitions at a section boundary.
 *
 * It REUSES the studio presentations (registry.build → presentation) and supplies
 * its OWN eased timing (an AGGRESSIVE ease-in-out by default) and, for the moving
 * transitions, an optional CameraMotionBlur wrap — the whole point: a crossfade's
 * easing is barely perceptible, but easing + motion blur carry real significance
 * on MOTION transitions at a section boundary. It then burns a corner label
 * (type / easing / duration) into the frame. Registered as a Composition in
 * Root.tsx; rendered headless via scripts/render-remotion.mjs
 * (--comp=FootageTransition ...) or the batch driver
 * scripts/render-footage-transitions.mjs. Never part of the video pipeline.
 *
 * Plain Remotion (no "use client"): consumed only by the Remotion bundler, so
 * siblings are imported by relative path.
 */
import { CameraMotionBlur } from "@remotion/motion-blur";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import type { CSSProperties } from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { getTransition, type TransitionParams } from "./registry";

/** Eased-timing curves selectable by id (the `easing` prop). Round 3 targets an
 *  AGGRESSIVE ease-in-out (`strongBezier` / `inOutQuint`) — a pronounced ease
 *  that does NOT rush the motion; the softer curves remain so a re-run can vary
 *  the shape with no code change. Deliberately NOT the studio's linear/spring
 *  timings. */
const EASINGS: Record<string, (t: number) => number> = {
  linear: Easing.linear,
  inCubic: Easing.in(Easing.cubic),
  outCubic: Easing.out(Easing.cubic),
  inOutSine: Easing.inOut(Easing.sin),
  inOutQuad: Easing.inOut(Easing.quad),
  inOutCubic: Easing.inOut(Easing.cubic),
  inOutQuart: Easing.inOut(Easing.poly(4)),
  inOutQuint: Easing.inOut(Easing.poly(5)),
  // A strong ease-in-out bezier: long flat ramp-in, steep middle, flat ramp-out
  // — the round-3 "aggressive" curve (pronounced ease, motion NOT rushed).
  strongBezier: Easing.bezier(0.83, 0, 0.17, 1),
};

/** Round-3 default curve (aggressive ease-in-out) when an unknown/empty easing
 *  id is passed; the render round drives each clip's easing explicitly. */
export const DEFAULT_EASING = "strongBezier";
/** ~1.2s on-screen hold per clip @30fps. */
export const DEFAULT_HOLD_FRAMES = 36;
/** ~0.6s transition @30fps. */
export const DEFAULT_TRANSITION_FRAMES = 18;
/** CameraMotionBlur shutter angle (0..360) when motionBlur is on — a
 *  pronounced-but-natural trail (180 = standard cinema). */
export const DEFAULT_SHUTTER_ANGLE = 200;
/** CameraMotionBlur sub-frame sample count when motionBlur is on. */
export const DEFAULT_MOTION_BLUR_SAMPLES = 12;

/** Fade-to-black (custom 3-phase) phase lengths @30fps — the round-4 "ref-match"
 *  timing measured off the user's reference clip: ~0.40s to ease clip A DOWN to
 *  full black, ~0.20s DWELL on pure black, ~0.25s to ease clip B UP from black.
 *  Only the `fadeToBlack` type reads these; every other type ignores them. */
export const DEFAULT_FADE_OUT_FRAMES = 12;
export const DEFAULT_BLACK_HOLD_FRAMES = 6;
export const DEFAULT_FADE_IN_FRAMES = 8;

/** Resolve an easing id to its curve, defaulting to ease-in-out cubic. */
function easingOf(id: string): (t: number) => number {
  return EASINGS[id] ?? EASINGS[DEFAULT_EASING];
}

/** Resolve a clip src for OffthreadVideo. http(s) URLs pass through; anything
 *  else is treated as a public/ path via staticFile() — the headless renderer
 *  serves public/ over http and CANNOT read `file://` URLs, so local clips must
 *  be staged into public/ (the batch driver does this). */
function resolveSrc(src: string): string {
  if (!src) return src;
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

/** Clamped transition length (frames) a params set resolves to. */
function transitionFramesOf(params: Partial<TransitionParams>): number {
  return Math.max(
    1,
    Math.round(params.durationInFrames ?? DEFAULT_TRANSITION_FRAMES),
  );
}

/** Shared cover-fit style for both clips, on BOTH render paths. */
const VIDEO_STYLE: CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

/** Burned-in bottom-left corner label (type / easing / timing). Shared by the
 *  studio-transition path and the custom fade-to-black path; null when empty. */
function labelOverlay(label: string) {
  if (!label) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 28,
          bottom: 28,
          padding: "10px 18px",
          borderRadius: 8,
          backgroundColor: "rgba(0,0,0,0.55)",
          color: "#fff",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 34,
          fontWeight: 600,
          letterSpacing: 0.5,
          lineHeight: 1.2,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
}

export type FootageTransitionProps = {
  /** Transition id from the studio registry (crossfade/slide/zoomBlur/fadeToBlack/…). */
  type: string;
  /** Studio params for the presentation; MERGED over the type's defaults, so a
   *  caller may pass only the knob(s) it cares about plus `durationInFrames`. */
  params: Partial<TransitionParams>;
  /** Clip A / B sources — a `file://` URL, http(s) URL, or staticFile() path. */
  clipA: string;
  clipB: string;
  /** Frames to skip into each source clip before its hold (pick a good moment). */
  trimA: number;
  trimB: number;
  /** On-screen hold per clip (frames) on its non-overlapping side. */
  holdFrames: number;
  /** Eased-timing curve id (see EASINGS). */
  easing: string;
  /** Burned-in corner label (e.g. "swipe/slide | strongBezier | 0.70s | +motionblur"). */
  label: string;
  /** When true, wrap the transition in CameraMotionBlur for real sub-frame
   *  motion blur — used on the MOVING transitions (slide/zoom). */
  motionBlur?: boolean;
  /** CameraMotionBlur shutter angle override (see DEFAULT_SHUTTER_ANGLE). */
  shutterAngle?: number;
  /** CameraMotionBlur sample-count override (see DEFAULT_MOTION_BLUR_SAMPLES). */
  samples?: number;
  /** Fade-to-black ONLY — frames for phase 1: clip A eases DOWN to full black. */
  fadeOutFrames?: number;
  /** Fade-to-black ONLY — frames the stage DWELLS on pure black (phase 2). */
  blackHoldFrames?: number;
  /** Fade-to-black ONLY — frames for phase 3: clip B eases UP from full black. */
  fadeInFrames?: number;
};

/** Total stage length. For a studio transition: two `hold + transition` clips
 *  overlapped by the transition, i.e. `transitionFrames + 2*hold`. For the custom
 *  fade-to-black: `2*hold + fadeOut + blackHold + fadeIn` — the pure-black DWELL
 *  is real extra time (neither clip shows), so it is ADDED, not overlapped. Root
 *  feeds this to calculateMetadata so a render's length matches the structure. */
export function footageDurationInFrames(props: {
  type?: string;
  params?: Partial<TransitionParams>;
  holdFrames?: number;
  fadeOutFrames?: number;
  blackHoldFrames?: number;
  fadeInFrames?: number;
}): number {
  const hold = Math.max(1, Math.round(props.holdFrames ?? DEFAULT_HOLD_FRAMES));
  if (props.type === "fadeToBlack") {
    const fadeOut = Math.max(
      0,
      Math.round(props.fadeOutFrames ?? DEFAULT_FADE_OUT_FRAMES),
    );
    const blackHold = Math.max(
      0,
      Math.round(props.blackHoldFrames ?? DEFAULT_BLACK_HOLD_FRAMES),
    );
    const fadeIn = Math.max(
      0,
      Math.round(props.fadeInFrames ?? DEFAULT_FADE_IN_FRAMES),
    );
    return 2 * hold + fadeOut + blackHold + fadeIn;
  }
  return transitionFramesOf(props.params ?? {}) + 2 * hold;
}

export const FootageTransition = ({
  type,
  params,
  clipA,
  clipB,
  trimA,
  trimB,
  holdFrames,
  easing,
  label,
  motionBlur,
  shutterAngle,
  samples,
  fadeOutFrames,
  blackHoldFrames,
  fadeInFrames,
}: FootageTransitionProps) => {
  const { width, height, fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const hold = Math.max(1, Math.round(holdFrames));

  // --- Fade-to-black: a CUSTOM 3-phase structure, NOT a duration-neutral
  // @remotion/transitions Transition. Those OVERLAP the two clips, so a hold on
  // pure black (where NEITHER clip shows) can't live inside one. Here clip A
  // holds, then keeps playing UNDER a black veil that eases 0→1 (settling ONTO
  // black), the frame DWELLS on pure black for `blackHoldFrames` (real extra
  // time in the middle), then clip B plays under the veil as it eases 1→0. Both
  // ramps run through `easingOf(easing)` (an ease-in-out) so the veil
  // DECELERATES onto black and eases back off it, instead of rushing the
  // midpoint the way the studio `fadeToBlack` presentation does.
  if (type === "fadeToBlack") {
    const fadeOut = Math.max(
      0,
      Math.round(fadeOutFrames ?? DEFAULT_FADE_OUT_FRAMES),
    );
    const blackHold = Math.max(
      0,
      Math.round(blackHoldFrames ?? DEFAULT_BLACK_HOLD_FRAMES),
    );
    const fadeIn = Math.max(0, Math.round(fadeInFrames ?? DEFAULT_FADE_IN_FRAMES));
    const ease = easingOf(easing);

    // Phase boundaries, in composition frames.
    const aFadeStart = hold; // clip A stops holding and begins easing to black
    const blackStart = aFadeStart + fadeOut; // full black reached
    const blackEnd = blackStart + blackHold; // end of the pure-black dwell
    const bHoldStart = blackEnd + fadeIn; // clip B fully revealed, begins holding
    const total = bHoldStart + hold; // end of stage

    // Black-veil opacity across the whole stage: eased 0→1 DOWN onto black, a
    // FLAT 1.0 dwell, then eased 1→0 back off. Each interpolate() is reached
    // only when its phase spans ≥1 frame (blackStart>aFadeStart /
    // bHoldStart>blackEnd), so a zero-length phase never hits interpolate.
    let veil: number;
    if (frame < aFadeStart) {
      veil = 0;
    } else if (frame < blackStart) {
      veil = interpolate(frame, [aFadeStart, blackStart], [0, 1], {
        easing: ease,
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else if (frame < blackEnd) {
      veil = 1;
    } else if (frame < bHoldStart) {
      veil = interpolate(frame, [blackEnd, bHoldStart], [1, 0], {
        easing: ease,
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else {
      veil = 0;
    }

    return (
      <AbsoluteFill style={{ backgroundColor: "black" }}>
        {/* Clip A: holds, then keeps playing UNDER the veil as it sinks to black. */}
        <Sequence from={0} durationInFrames={blackStart}>
          <AbsoluteFill>
            <OffthreadVideo
              src={resolveSrc(clipA)}
              trimBefore={Math.max(0, Math.round(trimA))}
              muted
              style={VIDEO_STYLE}
            />
          </AbsoluteFill>
        </Sequence>

        {/* Clip B: mounts as the dwell ends, plays UNDER the veil as it lifts. */}
        <Sequence
          from={blackEnd}
          durationInFrames={Math.max(1, total - blackEnd)}
        >
          <AbsoluteFill>
            <OffthreadVideo
              src={resolveSrc(clipB)}
              trimBefore={Math.max(0, Math.round(trimB))}
              muted
              style={VIDEO_STYLE}
            />
          </AbsoluteFill>
        </Sequence>

        {/* The PURE-BLACK veil: eased down onto black, flat dwell, eased back off. */}
        <AbsoluteFill style={{ backgroundColor: "#000", opacity: veil }} />

        {labelOverlay(label)}
      </AbsoluteFill>
    );
  }

  const def = getTransition(type);
  // Merge over the type's defaults so a caller can pass only the knob(s) + duration.
  const fullParams: TransitionParams = { ...def.defaultParams, ...params };
  // REUSE the studio presentation; DISCARD its (linear/spring) timing.
  const { presentation } = def.build({ params: fullParams, width, height, fps });

  const durationInFrames = transitionFramesOf(fullParams);
  // EASED timing — an aggressive ease-in-out by default. linearTiming reshapes
  // progress by `easing`, so the presentation sees an already-eased
  // presentationProgress.
  const timing = linearTiming({ durationInFrames, easing: easingOf(easing) });

  const seqFrames = durationInFrames + hold;

  const series = (
    <TransitionSeries>
      <TransitionSeries.Sequence durationInFrames={seqFrames}>
        <AbsoluteFill>
          <OffthreadVideo
            src={resolveSrc(clipA)}
            trimBefore={Math.max(0, Math.round(trimA))}
            muted
            style={VIDEO_STYLE}
          />
        </AbsoluteFill>
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={presentation} timing={timing} />
      <TransitionSeries.Sequence durationInFrames={seqFrames}>
        <AbsoluteFill>
          <OffthreadVideo
            src={resolveSrc(clipB)}
            trimBefore={Math.max(0, Math.round(trimB))}
            muted
            style={VIDEO_STYLE}
          />
        </AbsoluteFill>
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* Moving transitions (slide/zoom) get REAL sub-frame motion blur — the
          aggressive ease packs most of the travel into the middle frames, where
          CameraMotionBlur's per-frame displacement (and thus the smear) peaks. */}
      {motionBlur ? (
        <CameraMotionBlur
          shutterAngle={shutterAngle ?? DEFAULT_SHUTTER_ANGLE}
          samples={samples ?? DEFAULT_MOTION_BLUR_SAMPLES}
        >
          {series}
        </CameraMotionBlur>
      ) : (
        series
      )}

      {/* Burned-in corner label: type / easing / duration (+motionblur). */}
      {labelOverlay(label)}
    </AbsoluteFill>
  );
};
