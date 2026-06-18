"use client";

import { RunPanel } from "./RunPanel";
import { startVoiceover, startVisuals, startRender } from "@/lib/api";

type Stage = "voiceover" | "visuals" | "render";

const CONFIG = {
  voiceover: {
    starter: startVoiceover,
    buttonLabel: "Generate voiceover",
    runningLabel: "Generating audio...",
    completedLabel: "Voiceover ready",
    failedLabel: "Voiceover failed",
  },
  visuals: {
    starter: startVisuals,
    buttonLabel: "Fetch stock footage",
    runningLabel: "Fetching footage...",
    completedLabel: "Footage ready",
    failedLabel: "Footage fetch failed",
  },
  render: {
    starter: startRender,
    buttonLabel: "Render final video",
    runningLabel: "Rendering video... (~15–20 min)",
    completedLabel: "Render complete",
    failedLabel: "Render failed",
  },
} as const;

export function StageRunner({
  stage,
  slug,
  disabled,
  voiceSpeed,
}: {
  stage: Stage;
  slug: string;
  disabled?: boolean;
  /** Voiceover-only: override ElevenLabs speed for this run. */
  voiceSpeed?: number;
}) {
  const cfg = CONFIG[stage];
  const start =
    stage === "voiceover"
      ? () => startVoiceover(slug, { voice_speed: voiceSpeed })
      : () => cfg.starter(slug);
  return (
    <RunPanel
      start={start}
      buttonLabel={cfg.buttonLabel}
      runningLabel={cfg.runningLabel}
      completedLabel={cfg.completedLabel}
      failedLabel={cfg.failedLabel}
      disabled={disabled}
    />
  );
}
