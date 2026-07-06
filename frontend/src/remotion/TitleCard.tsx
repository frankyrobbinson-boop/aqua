import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * Placeholder title card: the title text fades in while dropping into place
 * over a diagonal gradient. Parameterized on `title` only — this is the single
 * composition source shared by the live Player preview and the MP4 renderer.
 *
 * Props are declared as a `type` (not an `interface`) on purpose: Remotion's
 * Player/Composition generics constrain composition props to
 * `Record<string, unknown>`, which a type-alias object literal satisfies but a
 * plain interface (no implicit index signature) does not.
 */
export type TitleCardProps = {
  title: string;
};

export const TitleCard = ({ title }: TitleCardProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Spring drives the vertical drop; a separate interpolate handles the fade so
  // the text reaches full opacity well before the spring fully settles.
  const entrance = spring({ frame, fps, config: { damping: 200 } });
  const translateY = interpolate(entrance, [0, 1], [60, 0]);
  const opacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background:
          "linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%)",
      }}
    >
      <h1
        style={{
          margin: 0,
          padding: "0 80px",
          textAlign: "center",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          fontSize: 120,
          fontWeight: 700,
          color: "white",
          opacity,
          transform: `translateY(${translateY}px)`,
        }}
      >
        {title}
      </h1>
    </AbsoluteFill>
  );
};
