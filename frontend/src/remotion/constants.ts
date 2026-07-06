/**
 * Shared render/preview constants for the Remotion motion-graphics module.
 * Imported by BOTH the live <Player> preview and the <Composition>s registered
 * for rendering, so the two can never drift on dimensions or frame rate.
 *
 * Duration is per-card now (props.durationInSeconds → durationInFrames via
 * calculateMetadata), so we keep only a shared DEFAULT here for the initial
 * Composition length and the form's starting value.
 */
export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const DEFAULT_DURATION_IN_SECONDS = 5;
