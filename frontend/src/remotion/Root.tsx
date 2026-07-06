import { Composition } from "remotion";

import { CARD_DEFAULTS } from "./cards/defaults";
import { CARDS } from "./cards/registry";
import { DEFAULT_DURATION_IN_SECONDS, FPS, HEIGHT, WIDTH } from "./constants";

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
          defaultProps={CARD_DEFAULTS}
          calculateMetadata={({ props }) => ({
            durationInFrames: Math.max(
              1,
              Math.round(props.durationInSeconds * FPS),
            ),
          })}
        />
      ))}
    </>
  );
};
