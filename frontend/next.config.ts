import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide the bottom-left dev indicator/devtools panel. Compile and runtime
  // errors still surface as overlays — only the persistent indicator is gone.
  devIndicators: false,
};

export default nextConfig;
