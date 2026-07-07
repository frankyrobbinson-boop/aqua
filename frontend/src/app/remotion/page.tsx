import type { Metadata } from "next";
import { RemotionWorkspace } from "@/components/RemotionWorkspace";

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
          Design garden title cards and preview them live, or browse the Lottie
          library to curate downloaded animations.
        </p>
      </div>
      <RemotionWorkspace />
    </div>
  );
}
