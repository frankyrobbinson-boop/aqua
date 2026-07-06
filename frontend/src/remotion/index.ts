import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

// Entry point for Remotion's bundler (see scripts/render-remotion.mjs). Not
// imported by the Next app — the Player consumes TitleCard directly.
registerRoot(RemotionRoot);
