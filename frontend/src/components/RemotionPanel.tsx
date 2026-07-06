"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import {
  remotionOutUrl,
  startRemotionRender,
  streamTaskLogs,
  type TaskStatus,
} from "@/lib/api";
import {
  DURATION_IN_FRAMES,
  FPS,
  HEIGHT,
  WIDTH,
} from "@/remotion/constants";
import { TitleCard } from "@/remotion/TitleCard";

// The Player touches browser-only APIs, so it must never render on the server.
// next/dynamic with ssr:false keeps it out of the SSR pass. The cast restores
// the generic Player type (erased by dynamic's loader) so `component` /
// `inputProps` stay type-checked against TitleCard's props. `typeof import(...)`
// is a type-only query — erased at compile time, no runtime import.
const Player = dynamic(
  () => import("@remotion/player").then((m) => m.Player),
  { ssr: false },
) as unknown as typeof import("@remotion/player").Player;

type RunState = {
  taskId: string;
  logs: string[];
  status: TaskStatus;
  filename: string;
};

export function RemotionPanel() {
  const [title, setTitle] = useState("Hello Aqua");
  const [run, setRun] = useState<RunState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Close any open SSE stream on unmount.
  useEffect(() => () => cleanupRef.current?.(), []);

  const running = submitting || run?.status === "running";

  async function onRender() {
    if (running) return;
    setError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      const { task_id, filename } = await startRemotionRender(title);
      setRun({ taskId: task_id, logs: [], status: "running", filename });
      cleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => setRun((prev) => (prev ? { ...prev, status } : prev)),
        (err) => setError(err instanceof Error ? err.message : String(err)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const videoUrl =
    run?.status === "completed" ? remotionOutUrl(run.filename) : null;

  return (
    <section className="space-y-6">
      <div className="rounded-xl border border-border bg-surface p-5">
        <label
          htmlFor="remotion-title"
          className="mb-2 block text-sm font-medium text-foreground"
        >
          Title
        </label>
        <input
          id="remotion-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          placeholder="Enter a title..."
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
        />

        <div className="mt-5 overflow-hidden rounded-lg border border-border bg-background">
          <Player
            component={TitleCard}
            inputProps={{ title }}
            durationInFrames={DURATION_IN_FRAMES}
            fps={FPS}
            compositionWidth={WIDTH}
            compositionHeight={HEIGHT}
            style={{ width: "100%", aspectRatio: "16 / 9" }}
            controls
            autoPlay
            loop
          />
        </div>

        <button
          type="button"
          onClick={onRender}
          disabled={running || title.trim().length === 0}
          className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
        >
          {submitting
            ? "Starting..."
            : run?.status === "running"
              ? "Rendering..."
              : "Render to MP4"}
        </button>

        {error && (
          <div className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
            {error}
          </div>
        )}
      </div>

      {run && (
        <div className="overflow-hidden rounded-lg border border-border bg-background">
          <div className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2">
            <span
              className={`h-2 w-2 rounded-full ${
                run.status === "completed"
                  ? "bg-success"
                  : run.status === "failed"
                    ? "bg-danger"
                    : "bg-accent animate-pulse"
              }`}
            />
            <span className="text-xs font-medium text-foreground">
              {run.status === "running"
                ? "Rendering..."
                : run.status === "completed"
                  ? "Render complete"
                  : run.status === "failed"
                    ? "Render failed"
                    : "Queued"}
            </span>
          </div>
          <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
            {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
          </pre>
        </div>
      )}

      {videoUrl && (
        <div className="rounded-xl border border-border bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-foreground">Result</h2>
          <video
            key={videoUrl}
            src={videoUrl}
            controls
            className="w-full rounded-lg border border-border bg-background"
            style={{ aspectRatio: "16 / 9" }}
          />
          <a
            href={videoUrl}
            download
            className="mt-4 inline-block rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
          >
            Download MP4
          </a>
        </div>
      )}
    </section>
  );
}
