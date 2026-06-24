"use client";

import { useEffect, useState } from "react";

/**
 * Tiny autosave status indicator: "Saving...", "Saved Xs ago", or
 * "Save failed". Ticks once a second while idle so the relative time stays
 * fresh without the parent having to re-render.
 */
export type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; at: number }
  | { kind: "error"; message: string };

export function ChannelStatusBar({ state }: { state: SaveState }) {
  // Re-render every second so "Saved Xs ago" stays current.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (state.kind !== "saved") return;
    const handle = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(handle);
  }, [state.kind]);

  let body: React.ReactNode;
  let tone = "text-muted";
  if (state.kind === "idle") {
    body = "Edits save automatically.";
  } else if (state.kind === "saving") {
    body = "Saving...";
    tone = "text-foreground";
  } else if (state.kind === "saved") {
    body = `Saved ${formatAgo(Date.now() - state.at)} ago`;
  } else {
    body = `Save failed: ${state.message}`;
    tone = "text-danger";
  }

  return <span className={`text-xs ${tone}`}>{body}</span>;
}

function formatAgo(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  return `${hr}h`;
}
