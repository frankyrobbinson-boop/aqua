import { Composition } from "remotion";

import { CARD_DEFAULTS, CARD_DEFAULT_OVERRIDES } from "./cards/defaults";
import { CARDS } from "./cards/registry";
import { DEFAULT_DURATION_IN_SECONDS, FPS, HEIGHT, WIDTH } from "./constants";
import { LottiePreview } from "./LottiePreview";
import {
  DEFAULT_BLACK_HOLD_FRAMES,
  DEFAULT_FADE_IN_FRAMES,
  DEFAULT_FADE_OUT_FRAMES,
  FootageTransition,
  footageDurationInFrames,
} from "./transitions/FootageTransition";
import { TRANSITIONS } from "./transitions/registry";
import {
  previewDurationInFrames,
  TransitionPreview,
} from "./transitions/TransitionPreview";

/** Fixed length for the looping Lottie evaluation stage (see LottiePreview). */
const LOTTIE_PREVIEW_FRAMES = 120;
/** Fallback length for the two-clip transition preview stage (TransitionPreview).
 *  The live Player and the render-preview both derive the real length from the
 *  props (transition duration + hold) — the Player directly, a render via
 *  calculateMetadata below; this is just the registered default. */
const TRANSITION_PREVIEW_FRAMES = 90;

/**
 * Remotion root registered by index.ts. Exposes one <Composition> per garden
 * title card (see cards/registry.ts). Dimensions / fps come from the shared
 * constants so preview and render stay in lockstep; each card's length is
 * derived per-render from `props.durationInSeconds` via calculateMetadata.
 * Siblings are imported by RELATIVE path because Remotion's bundler resolves
 * this tree without the app's `@/*` path alias.
 */
export const RemotionRoot = () => {
  return (
    <>
      {CARDS.map((card) => (
        <Composition
          key={card.id}
          id={card.id}
          component={card.component}
          durationInFrames={Math.round(DEFAULT_DURATION_IN_SECONDS * FPS)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{
            ...CARD_DEFAULTS,
            ...(CARD_DEFAULT_OVERRIDES[card.id] ?? {}),
          }}
          calculateMetadata={({ props }) => ({
            durationInFrames: Math.max(
              1,
              Math.round(props.durationInSeconds * FPS),
            ),
          })}
        />
      ))}

      {/* Curation stage: loops one downloaded Lottie on a garden wash. Not a
          card — the /remotion "Lottie Library" tab drives it via the Player. */}
      <Composition
        id="LottiePreview"
        component={LottiePreview}
        durationInFrames={LOTTIE_PREVIEW_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{ animationData: null }}
      />

      {/* Transition preview: two sample clips bridged by a chosen transition.
          Not a card and NOT in the backend's ALLOWED_COMPS — the /remotion
          "Transitions" tab drives it via the Player; registered here (like
          LottiePreview) for parity, never rendered to MP4. */}
      <Composition
        id="TransitionPreview"
        component={TransitionPreview}
        durationInFrames={TRANSITION_PREVIEW_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{
          type: TRANSITIONS[0].id,
          params: TRANSITIONS[0].defaultParams,
        }}
        calculateMetadata={({ props }) => ({
          durationInFrames: previewDurationInFrames(
            props.params,
            props.holdFrames,
          ),
        })}
      />

      {/* Footage-to-footage transition stage: two REAL clips bridged by a chosen
          studio transition with EASED timing (see FootageTransition). Not a card
          and NOT in the backend's ALLOWED_COMPS — rendered headless via
          scripts/render-remotion.mjs (--comp=FootageTransition) or the batch
          driver scripts/render-footage-transitions.mjs to produce rating clips. */}
      <Composition
        id="FootageTransition"
        component={FootageTransition}
        durationInFrames={90}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{
          type: "crossfade",
          params: {},
          clipA: "",
          clipB: "",
          trimA: 0,
          trimB: 0,
          holdFrames: 36,
          easing: "strongBezier",
          label: "",
          motionBlur: false,
          fadeOutFrames: DEFAULT_FADE_OUT_FRAMES,
          blackHoldFrames: DEFAULT_BLACK_HOLD_FRAMES,
          fadeInFrames: DEFAULT_FADE_IN_FRAMES,
        }}
        calculateMetadata={({ props }) => ({
          durationInFrames: footageDurationInFrames(props),
        })}
      />
    </>
  );
};
