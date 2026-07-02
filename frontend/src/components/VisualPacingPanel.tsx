"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { invalidateForProject } from "@/lib/invalidation";
import { SegmentVisualRow } from "./SegmentVisualRow";
import { ScenePreview } from "./ScenePreview";
import {
  VisualTimelineBar,
  type TimelineSegment,
} from "./VisualTimelineBar";
import {
  API_URL,
  getVisualPromptStatus,
  regenerateScene,
  regenerateVisualPrompts,
  setSceneVisualMode,
  startFootageRefetch,
  startVisualsGenerate,
  streamTaskLogs,
  updateVisualConfig,
  type SceneInfo,
  type SceneOverrides,
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
  // Per-scene overrides for "mixed" segments. Persisted via its own endpoint on
  // toggle, but also round-tripped through the segment PUT so the debounced
  // segment autosave (which rewrites the whole file) can't wipe them. A ref
  // mirrors the state so the autosave effect reads the latest without taking a
  // dependency on it (which would otherwise fire a PUT on every toggle).
  const [sceneOverrides, setSceneOverrides] = useState<SceneOverrides>(
    initialConfig.config.scene_overrides ?? {},
  );
  const sceneOverridesRef = useRef(sceneOverrides);
  useEffect(() => {
    sceneOverridesRef.current = sceneOverrides;
  }, [sceneOverrides]);
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
      updateVisualConfig(slug, segments, sceneOverridesRef.current).catch(
        (err) => {
          setSaveError(err instanceof Error ? err.message : String(err));
        },
      );
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

  const totalScenes = segments.reduce((sum, s) => sum + (s.scene_count ?? 0), 0);
  const canGenerate = !submitting && run?.status !== "running";

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

  // Shared run dispatch: flush pending config edits, kick off whichever runner
  // ``starter`` names (full visuals re-plan vs. footage-only refetch), then
  // stream its logs. Both paths hit the same task SSE plumbing.
  async function startRun(starter: () => Promise<{ task_id: string }>) {
    if (!canGenerate) return;
    setSaveError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      // Flush any pending edits before kicking off the run so the worker sees
      // the latest config.
      await updateVisualConfig(slug, segments, sceneOverridesRef.current);
      const { task_id } = await starter();
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

  // Full pipeline: re-plans scenes from the script (costs an LLM call), then
  // recomputes windows/prompts and re-fetches all footage.
  const onGenerate = () => startRun(() => startVisualsGenerate(slug));
  // Footage-only: keeps the existing scene plan, fills missing/changed clips.
  const onRefetch = () => startRun(() => startFootageRefetch(slug));

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
        <p className="text-xs text-muted">
          Per-segment mode and provider. Edits save automatically.
        </p>
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
              {promptRun?.status === "running"
                ? "Regenerating prompts..."
                : "Regenerate prompts"}
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
          No scenes yet — click Generate to plan scenes from your script and
          fetch footage. You can fine-tune per-segment modes and providers after
          this first run.
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

      {scenes.length === 0 ? (
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
              : totalScenes > 0
                ? `Generate ${totalScenes} Scene${totalScenes === 1 ? "" : "s"}`
                : "Generate Scenes"}
        </button>
      ) : (
        <div className="mt-5 space-y-2">
          <button
            type="button"
            onClick={onRefetch}
            disabled={!canGenerate}
            className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
          >
            {submitting
              ? "Starting..."
              : run?.status === "running"
                ? "Generating visuals..."
                : "Refetch footage"}
          </button>
          <button
            type="button"
            onClick={onGenerate}
            disabled={!canGenerate}
            className="w-full rounded-md border border-border bg-surface px-4 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:text-muted"
          >
            Re-plan from script
          </button>
          <p className="text-[10px] text-muted">
            Refetch keeps your scene plan and fills missing/changed clips.
            Re-plan regenerates the scene plan from the script (costs an LLM
            call).
          </p>
        </div>
      )}

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

      {scenes.length > 0 && (
        <div className="mt-8 space-y-5 border-t border-border pt-6">
          <h3 className="text-sm font-medium text-foreground">Scene previews</h3>
          {segments.map((seg, i) => {
            const segScenes = scenes.filter(
              (s) => s.segment_id === seg.segment_id,
            );
            if (segScenes.length === 0) return null;
            const mixed = seg.mode === "mixed";
            const aiCount = mixed
              ? segScenes.filter(
                  (s) => effectiveMode(s, sceneOverrides) === "ai_image",
                ).length
              : 0;
            return (
              <div key={seg.segment_id}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-xs font-medium text-muted">
                    {segmentLabel(seg.segment_id, i, segments.length)}
                  </p>
                  {mixed && (
                    <p className="text-[10px] text-muted">
                      {aiCount} AI image{aiCount === 1 ? "" : "s"} · ~$
                      {(aiCount * 0.039).toFixed(2)} (Nano Banana, $0.039/image)
                    </p>
                  )}
                </div>
                <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
                  {segScenes.map((s) => (
                    <ScenePreviewTile
                      key={s.id}
                      slug={slug}
                      scene={s}
                      mixed={mixed}
                      effective={effectiveMode(s, sceneOverrides)}
                      onModeChange={(mode) =>
                        setSceneOverrides((prev) => ({
                          ...prev,
                          [String(s.id)]: mode,
                        }))
                      }
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** Effective per-scene mode for the wizard's local view: a local/persisted
 *  override wins, then the backend-computed scene mode, then stock_video. */
function effectiveMode(
  scene: SceneInfo,
  overrides: SceneOverrides,
): "stock_video" | "ai_image" {
  const o = overrides[String(scene.id)];
  if (o === "stock_video" || o === "ai_image") return o;
  if (scene.visual_mode === "ai_image") return "ai_image";
  return "stock_video";
}

/** One scene tile in the wizard preview grid. For a mixed segment it shows a
 *  Stock/AI toggle that persists the override then regenerates the footage in
 *  place (the backend pre-deletes the old .png/.mp4 on a flip). */
function ScenePreviewTile({
  slug,
  scene,
  mixed,
  effective,
  onModeChange,
}: {
  slug: string;
  scene: SceneInfo;
  mixed: boolean;
  effective: "stock_video" | "ai_image";
  onModeChange: (mode: "stock_video" | "ai_image") => void;
}) {
  const [bust, setBust] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const baseUrl = scene.footage_url ? `${API_URL}${scene.footage_url}` : null;
  const url = baseUrl && bust > 0 ? `${baseUrl}?v=${bust}` : baseUrl;

  async function choose(mode: "stock_video" | "ai_image") {
    if (busy || mode === effective) return;
    setErr(null);
    setBusy(true);
    try {
      await setSceneVisualMode(slug, scene.id, mode);
      onModeChange(mode);
      await regenerateScene(slug, scene.id);
      setBust((n) => n + 1);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function regenerate() {
    if (busy) return;
    setErr(null);
    setBusy(true);
    try {
      await regenerateScene(slug, scene.id);
      setBust((n) => n + 1);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="relative aspect-video bg-background">
        <ScenePreview
          url={url}
          alt={scene.visual_description || `Scene ${scene.id}`}
        />
        <span className="absolute left-2 top-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-muted">
          #{scene.id}
        </span>
        {mixed ? (
          <div className="absolute bottom-2 left-2 flex gap-1">
            {(["stock_video", "ai_image"] as const).map((m) => (
              <button
                key={m}
                type="button"
                disabled={busy}
                onClick={() => choose(m)}
                className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
                  effective === m
                    ? "bg-accent text-white"
                    : "bg-background/80 text-muted hover:text-foreground"
                } ${busy ? "cursor-not-allowed opacity-60" : ""}`}
              >
                {m === "stock_video" ? "Stock" : "AI"}
              </button>
            ))}
            {/* Re-fetch this scene on its current mode — lets a failed clip
                (already on the right mode) be retried without flipping. */}
            <button
              type="button"
              disabled={busy}
              onClick={regenerate}
              className={`rounded bg-background/80 px-1.5 py-0.5 text-[10px] font-medium text-muted transition-colors hover:text-foreground ${
                busy ? "cursor-not-allowed opacity-60" : ""
              }`}
            >
              Regenerate
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={regenerate}
            className={`absolute bottom-2 left-2 rounded bg-background/80 px-1.5 py-0.5 text-[10px] font-medium text-muted transition-colors hover:text-foreground ${
              busy ? "cursor-not-allowed opacity-60" : ""
            }`}
          >
            Regenerate
          </button>
        )}
        {busy && (
          <span className="absolute bottom-2 right-2 rounded bg-background/80 px-1.5 py-0.5 text-[10px] text-muted">
            Working…
          </span>
        )}
      </div>
      <div className="p-2">
        <p className="line-clamp-1 text-[11px] text-foreground">
          {scene.visual_description || "(no query)"}
        </p>
        {err && <p className="mt-0.5 text-[10px] text-danger">{err}</p>}
      </div>
    </div>
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
    const take = Math.min(seg.scene_count ?? 0, scenes.length - cursor);
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
