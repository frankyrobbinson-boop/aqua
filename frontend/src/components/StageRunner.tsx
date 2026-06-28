"use client";

import { RunPanel } from "./RunPanel";
import {
  startVoiceover,
  startVisuals,
  startRender,
  type RenderOptions,
} from "@/lib/api";

type Stage = "voiceover" | "visuals" | "render";

const STAGE_LIST: Record<Stage, string[]> = {
  voiceover: ["tts_prep", "voice_units", "delivery_plan", "audio"],
  visuals: ["scene_plan", "scene_windows", "visual_prompts", "footage"],
  render: ["edl", "render"],
};

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
  renderOptions,
}: {
  stage: Stage;
  slug: string;
  disabled?: boolean;
  /** Voiceover-only: override ElevenLabs speed for this run. */
  voiceSpeed?: number;
  /** Render-only: per-render transition + Ken Burns flags. */
  renderOptions?: RenderOptions;
}) {
  const cfg = CONFIG[stage];
  let start: () => ReturnType<typeof cfg.starter>;
  if (stage === "voiceover") {
    start = () => startVoiceover(slug, { voice_speed: voiceSpeed });
  } else if (stage === "render") {
    start = () => startRender(slug, renderOptions);
  } else {
    start = () => cfg.starter(slug);
  }
  return (
    <RunPanel
      start={start}
      buttonLabel={cfg.buttonLabel}
      runningLabel={cfg.runningLabel}
      completedLabel={cfg.completedLabel}
      failedLabel={cfg.failedLabel}
      disabled={disabled}
      stage={stage}
      projectSlug={slug}
      stageList={STAGE_LIST[stage]}
    />
  );
}
