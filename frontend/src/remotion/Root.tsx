import { Composition } from "remotion";
import { TitleCard } from "./TitleCard";
import { DURATION_IN_FRAMES, FPS, HEIGHT, WIDTH } from "./constants";

/**
 * Remotion root registered by index.ts. Exposes a single composition
 * (`TitleCard`) whose dimensions / fps / duration come from the shared
 * constants so preview and render stay in lockstep. Siblings are imported by
 * RELATIVE path because Remotion's bundler resolves this tree without the app's
 * `@/*` path alias.
 */
export const RemotionRoot = () => {
  return (
    <Composition
      id="TitleCard"
      component={TitleCard}
      durationInFrames={DURATION_IN_FRAMES}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ title: "Hello Aqua" }}
    />
  );
};
