"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { invalidateForProject } from "@/lib/invalidation";
import { SegmentVisualRow } from "./SegmentVisualRow";
import {
  VisualTimelineBar,
  type TimelineSegment,
} from "./VisualTimelineBar";
import {
  getVisualPromptStatus,
  regenerateVisualPrompts,
  startVisualsGenerate,
  streamTaskLogs,
  updateVisualConfig,
  type SceneInfo,
  type TaskStatus,
  type VisualConfigResponse,
  type VisualPromptStatus,
  type VisualProvidersResponse,
  type VisualSegmentConfig,
} from "@/lib/api";

/**
 * Step 3 of the Generate Visuals wizard. Owns the editable visual_config
 * (the per-segment mode + provider + scene_count grid) and the action that
 * dispatches the actual generation run.
 *
 * Saves are debounced (~600 ms): a knob change writes to local state, then
 * fires a PUT after the user stops fiddling, so we don't slam the API on
 * every keystroke of the scene-count input. The generate button always saves
 * first to guarantee the run sees the latest config.
 */
type Props = {
  slug: string;
  scenes: SceneInfo[];
  providers: VisualProvidersResponse;
  initialConfig: VisualConfigResponse;
};

type RunState = {
  taskId: string;
  logs: string[];
  status: TaskStatus;
};

export function VisualPacingPanel({
  slug,
  scenes,
  providers,
  initialConfig,
}: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [segments, setSegments] = useState<VisualSegmentConfig[]>(
    initialConfig.config.segments,
  );
  const [advanced, setAdvanced] = useState(true);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Visual-prompt status (pre-generation enhancement step). Polled once on
  // mount and refreshed after a regenerate completes. Errors are swallowed —
  // the panel still works without the status line.
  const [promptStatus, setPromptStatus] = useState<VisualPromptStatus | null>(
    null,
  );
  const [promptRun, setPromptRun] = useState<RunState | null>(null);
  const promptCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVisualPromptStatus(slug)
      .then((s) => {
        if (!cancelled) setPromptStatus(s);
      })
      .catch(() => {
        // Non-fatal: leave promptStatus null and skip rendering the line.
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => () => promptCleanupRef.current?.(), []);

  // Debounce-save when segments change. Skip the initial mount so we don't
  // PUT the server's own response right back at it.
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    const handle = setTimeout(() => {
      updateVisualConfig(slug, segments).catch((err) => {
        setSaveError(err instanceof Error ? err.message : String(err));
      });
    }, 600);
    return () => clearTimeout(handle);
  }, [segments, slug]);

  // Clean up any open SSE stream on unmount.
  const cleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanupRef.current?.(), []);

  // Map config segments → time ranges by walking scenes in narrative order
  // (scene_plan ordering matches visual_config ordering: hook, body 0..N,
  // conclusion). Counted using the LIVE scene array, not the config's
  // scene_count, because the rendered scenes are the source of truth for
  // timing. If counts disagree, we still produce the best-effort range.
  const segmentTimings = useMemo(
    () => deriveSegmentTimings(scenes, segments),
    [scenes, segments],
  );

  const totalScenes = segments.reduce((sum, s) => sum + s.scene_count, 0);
  const canGenerate =
    segments.length > 0 && !submitting && run?.status !== "running";

  async function onRegeneratePrompts() {
    promptCleanupRef.current?.();
    try {
      const { task_id } = await regenerateVisualPrompts(slug);
      setPromptRun({ taskId: task_id, logs: [], status: "running" });
      promptCleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setPromptRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => {
          setPromptRun((prev) => (prev ? { ...prev, status } : prev));
          // Refresh status snapshot once the run settles.
          getVisualPromptStatus(slug)
            .then((s) => setPromptStatus(s))
            .catch(() => {});
        },
      );
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onGenerate() {
    if (!canGenerate) return;
    setSaveError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      // Flush any pending edits before kicking off the run so the worker sees
      // the latest config.
      await updateVisualConfig(slug, segments);
      const { task_id } = await startVisualsGenerate(slug);
      setRun({ taskId: task_id, logs: [], status: "running" });
      cleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => {
          setRun((prev) => (prev ? { ...prev, status } : prev));
          if (status === "completed") {
            invalidateForProject(queryClient, slug, router);
          }
        },
      );
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const timelineSegments: TimelineSegment[] = segments
    .map((seg, i) => {
      const t = segmentTimings[i];
      if (!t) return null;
      return {
        key: String(seg.segment_id),
        label: segmentLabel(seg.segment_id, i, segments.length),
        start: t.start,
        end: t.end,
      };
    })
    .filter((x): x is TimelineSegment => x !== null);

  return (
    <section className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-foreground">
            Step 3: Visual Pacing
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            Per-segment mode and provider. Edits save automatically.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
          <span>Advanced</span>
          <button
            type="button"
            onClick={() => setAdvanced((v) => !v)}
            aria-pressed={advanced}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              advanced ? "bg-accent" : "bg-surface-3"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                advanced ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </label>
      </div>

      <div className="mb-5">
        <VisualTimelineBar segments={timelineSegments} />
      </div>

      {promptStatus && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-border bg-surface/40 px-3 py-2 text-xs text-muted">
          <span className="truncate">
            {promptStatus.exists
              ? `Prompts: ${promptStatus.scene_count} generated · ${promptStatus.model ?? "?"} · ${promptStatus.source ?? "?"} · ${formatRelativeTime(promptStatus.generated_at)}`
              : "Prompts: not generated yet — will run automatically when you click Generate Scenes."}
          </span>
          {promptStatus.exists && (
            <button
              type="button"
              onClick={onRegeneratePrompts}
              disabled={promptRun?.status === "running"}
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-foreground hover:bg-surface-2 disabled:cursor-not-allowed disabled:text-muted"
            >
              {promptRun?.status === "running" ? "Regenerating..." : "Regenerate"}
            </button>
          )}
        </div>
      )}

      {promptRun && (
        <div className="mb-3 overflow-hidden rounded-lg border border-border bg-background">
          <div className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2">
            <span
              className={`h-2 w-2 rounded-full ${
                promptRun.status === "completed"
                  ? "bg-success"
                  : promptRun.status === "failed"
                    ? "bg-danger"
                    : "bg-accent animate-pulse"
              }`}
            />
            <span className="text-xs font-medium text-foreground">
              {promptRun.status === "running"
                ? "Regenerating prompts..."
                : promptRun.status === "completed"
                  ? "Prompts ready"
                  : promptRun.status === "failed"
                    ? "Prompt regeneration failed"
                    : "Queued"}
            </span>
          </div>
          <pre className="max-h-48 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
            {promptRun.logs.length === 0
              ? "Waiting for output..."
              : promptRun.logs.join("\n")}
          </pre>
        </div>
      )}

      {segments.length === 0 ? (
        <div className="rounded-md border border-dashed border-border bg-surface/40 p-6 text-center text-sm text-muted">
          No scene plan yet. Generate a script first, then return here to
          configure visuals.
        </div>
      ) : (
        <div className="space-y-3">
          {segments.map((seg, i) => (
            <SegmentVisualRow
              key={seg.segment_id}
              segment={seg}
              label={segmentLabel(seg.segment_id, i, segments.length)}
              timeRange={segmentTimings[i]}
              modes={providers.modes}
              providers={providers.providers}
              onChange={(next) =>
                setSegments((prev) =>
                  prev.map((s, j) => (j === i ? next : s)),
                )
              }
              disabled={run?.status === "running"}
            />
          ))}
        </div>
      )}

      {saveError && (
        <div className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
          {saveError}
        </div>
      )}

      <button
        type="button"
        onClick={onGenerate}
        disabled={!canGenerate}
        className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
      >
        {submitting
          ? "Starting..."
          : run?.status === "running"
            ? "Generating visuals..."
            : `Generate ${totalScenes} Scene${totalScenes === 1 ? "" : "s"}`}
      </button>

      {run && (
        <div className="mt-4 overflow-hidden rounded-lg border border-border bg-background">
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
                ? "Generating visuals..."
                : run.status === "completed"
                  ? "Generation complete — scene cards updated"
                  : run.status === "failed"
                    ? "Generation failed"
                    : "Queued"}
            </span>
          </div>
          <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
            {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
          </pre>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compact relative-time formatter for the prompt-status row. */
function formatRelativeTime(iso: string | null): string {
  if (!iso) return "unknown time";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "unknown time";
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

/** Human-readable label for a segment. Matches scene_plan conventions:
 *  -1 = hook, -2 = conclusion, otherwise "Segment N" (1-indexed). */
function segmentLabel(
  segmentId: number,
  positionInList: number,
  totalCount: number,
): string {
  if (segmentId === -1) return "Hook";
  if (segmentId === -2) return "Conclusion";
  // Body segments may be 0-indexed in the data but humans count from 1. If
  // the segment is sandwiched between hook (first) and conclusion (last),
  // derive the body number from its position rather than the raw id.
  const bodyNumber = positionInList; // hook is at index 0
  if (positionInList > 0 && positionInList < totalCount - 1) {
    return `Segment ${bodyNumber}`;
  }
  return `Segment ${segmentId + 1}`;
}

/** Compute [start, end] per config segment by counting scenes in order.
 *  Returns null for a segment when timing is unavailable (no scenes yet, or
 *  scenes lack start/end). */
function deriveSegmentTimings(
  scenes: SceneInfo[],
  segments: VisualSegmentConfig[],
): Array<{ start: number; end: number } | null> {
  const result: Array<{ start: number; end: number } | null> = [];
  if (scenes.length === 0) {
    return segments.map(() => null);
  }
  let cursor = 0;
  for (const seg of segments) {
    const take = Math.min(seg.scene_count, scenes.length - cursor);
    if (take <= 0) {
      result.push(null);
      continue;
    }
    const slice = scenes.slice(cursor, cursor + take);
    const startTimes = slice
      .map((s) => s.start_time)
      .filter((t): t is number => t != null);
    const endTimes = slice
      .map((s) => s.end_time)
      .filter((t): t is number => t != null);
    if (startTimes.length === 0 || endTimes.length === 0) {
      result.push(null);
    } else {
      result.push({
        start: Math.min(...startTimes),
        end: Math.max(...endTimes),
      });
    }
    cursor += take;
  }
  return result;
}
