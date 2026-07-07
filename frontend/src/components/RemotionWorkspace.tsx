"use client";

import { useState } from "react";

import { LottieLibrary } from "@/components/LottieLibrary";
import { RemotionPanel } from "@/components/RemotionPanel";

/**
 * Top-level switch for the /remotion tab: the existing "Cards" title-card
 * designer, or the new "Lottie Library" curation view. Lives in a client
 * component so page.tsx can stay a server component (it owns the metadata +
 * header). RemotionPanel is rendered unchanged under "Cards".
 */
type Mode = "cards" | "lottie";

const MODES: ReadonlyArray<{ id: Mode; label: string }> = [
  { id: "cards", label: "Cards" },
  { id: "lottie", label: "Lottie Library" },
];

export function RemotionWorkspace() {
  const [mode, setMode] = useState<Mode>("cards");
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {MODES.map(({ id, label }) => {
          const active = id === mode;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              aria-pressed={active}
              className={`rounded-md border px-3.5 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border bg-surface text-muted hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {mode === "cards" ? <RemotionPanel /> : <LottieLibrary />}
    </div>
  );
}
