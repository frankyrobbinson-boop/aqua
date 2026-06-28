"use client";

import type { StageEvent, TaskStatus } from "@/lib/api";

type Props = {
  stages: string[];
  events: StageEvent[];
  terminalStatus: TaskStatus | null;
};

type StageState = "pending" | "in-progress" | "completed" | "failed";

function computeState(
  stage: string,
  events: StageEvent[],
  terminalStatus: TaskStatus | null,
): StageState {
  const started = events.some((e) => e.stage === stage && e.status === "started");
  const completed = events.some(
    (e) => e.stage === stage && e.status === "completed",
  );
  if (completed) return "completed";
  if (started) {
    // Started but not completed — the run ended on this stage if terminal status
    // is failed; otherwise it's still actively in-progress.
    if (terminalStatus === "failed") return "failed";
    return "in-progress";
  }
  return "pending";
}

export function StageList({ stages, events, terminalStatus }: Props) {
  return (
    <ul className="space-y-1.5">
      {stages.map((stage) => {
        const state = computeState(stage, events, terminalStatus);
        return (
          <li
            key={stage}
            className="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm"
          >
            <StageIcon state={state} />
            <span
              className={
                state === "completed"
                  ? "text-foreground"
                  : state === "in-progress"
                    ? "text-foreground font-medium"
                    : state === "failed"
                      ? "text-danger font-medium"
                      : "text-muted"
              }
            >
              {stage}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function StageIcon({ state }: { state: StageState }) {
  if (state === "completed") {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-success text-[10px] font-bold text-white">
        {"✓"}
      </span>
    );
  }
  if (state === "in-progress") {
    return (
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
    );
  }
  if (state === "failed") {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-danger text-[10px] font-bold text-white">
        {"✕"}
      </span>
    );
  }
  return <span className="h-2 w-2 rounded-full bg-muted" />;
}
