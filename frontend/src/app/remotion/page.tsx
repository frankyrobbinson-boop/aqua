import type { Metadata } from "next";
import { RemotionPanel } from "@/components/RemotionPanel";

export const metadata: Metadata = {
  title: "Remotion · Aqua",
};

export default function RemotionPage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Remotion
        </h1>
        <p className="mt-1 text-sm text-muted">
          Design a garden title card — pick a layout, tune the palette, motion,
          and botanicals, preview it live, then render it to an MP4.
        </p>
      </div>
      <RemotionPanel />
    </div>
  );
}
