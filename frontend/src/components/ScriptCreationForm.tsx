"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  createScript,
  createPipeline,
  getVisualProviders,
  streamTaskLogs,
  type ScriptRequest,
  type StageEvent,
  type TaskStatus,
  type VisualProvider,
} from "@/lib/api";
import { invalidateForProject } from "@/lib/invalidation";

import { ChannelSelect } from "@/components/ChannelSelect";
import { HookArchetypeSelect } from "@/components/HookArchetypeSelect";
import { RenderConfigPanel } from "@/components/RenderConfigPanel";
import { StageList } from "@/components/StageList";
import { VideoTypeSelect } from "@/components/VideoTypeSelect";

// Video types whose sections are a countable item list — these expose the
// "Number of items" control and send item_count. Mirrors the backend registry.
const LIST_TYPES = ["mistakes", "discovery_list"];

const SCRIPT_STAGES = ["research", "outline", "script_draft"];
const PIPELINE_STAGES = [
  "research",
  "outline",
  "script_draft",
  "tts_prep",
  "voice_units",
  "delivery_plan",
  "audio",
  "scene_plan",
  "scene_windows",
  "visual_prompts",
  "footage",
  "edl",
  "render",
];

/**
 * Single canonical script-creation form used by both /projects/new (creation)
 * and /projects/[slug] (resuming a draft with no script yet). Fields here are
 * the per-video knobs that affect script generation; voice speed lives on the
 * Voiceover tab (channel preset will own its default once channels land).
 */
export type ScriptCreationFormProps = {
  /** When set, the script generates into this existing project slug.
   * When unset, the API derives a slug from the topic and creates a new project. */
  projectSlug?: string;
  /** Called when a run completes (or fails) with the resolved slug.
   * /projects/new uses it to navigate to /projects/[slug] on success;
   * /projects/[slug] uses it to refresh the page data. */
  onRunComplete?: (projectSlug: string, status: TaskStatus) => void;
};

export function ScriptCreationForm({
  projectSlug,
  onRunComplete,
}: ScriptCreationFormProps) {
  const [topic, setTopic] = useState("");
  const [targetMinutes, setTargetMinutes] = useState(10);
  const [videoType, setVideoType] = useState<string | undefined>(undefined);
  const [itemCount, setItemCount] = useState(5);
  const [preResearch, setPreResearch] = useState("");
  const [additionalInstructions, setAdditionalInstructions] = useState("");
  const [sampleScript, setSampleScript] = useState("");
  const [channel, setChannel] = useState<string | undefined>(undefined);
  const [hookArchetype, setHookArchetype] = useState<string | undefined>(
    undefined,
  );

  // Full-pipeline-only options: only sent when the "Run full pipeline" button
  // is used. Render defaults mirror the render tab (RenderTab in ProjectView).
  const [visualProvider, setVisualProvider] = useState("seedream");
  const [providers, setProviders] = useState<VisualProvider[]>([]);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [sectionTransitions, setSectionTransitions] = useState(true);
  const [sectionCards, setSectionCards] = useState(true);
  const [kenBurns, setKenBurns] = useState(false);
  const [music, setMusic] = useState(false);
  const [musicVolume, setMusicVolume] = useState(0.05);

  useEffect(() => {
    let mounted = true;
    getVisualProviders()
      .then((res) => {
        if (!mounted) return;
        const available = res.providers.filter((p) => p.available);
        setProviders(available);
        // Defensive: if the default ever leaves the registry, fall back to the
        // first available provider so the dropdown never sits on a dead value.
        if (
          available.length > 0 &&
          !available.some((p) => p.id === "seedream")
        ) {
          setVisualProvider(available[0].id);
        }
      })
      .catch((err) => {
        if (mounted)
          setProvidersError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      mounted = false;
    };
  }, []);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [run, setRun] = useState<{
    projectSlug: string;
    logs: string[];
    stageEvents: StageEvent[];
    status: TaskStatus;
    mode: "script" | "pipeline";
  } | null>(null);

  const router = useRouter();
  const queryClient = useQueryClient();

  const cleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanupRef.current?.(), []);

  const canSubmit =
    topic.trim().length > 0 && !submitting && run?.status !== "running";

  async function onRun(mode: "script" | "pipeline") {
    if (!canSubmit) return;
    setSubmitError(null);
    setSubmitting(true);
    cleanupRef.current?.();

    const body: ScriptRequest = {
      topic: topic.trim(),
      target_minutes: targetMinutes,
      project_slug: projectSlug,
      video_type: videoType,
      // Item count applies to both list video types; omit for any other type.
      item_count: LIST_TYPES.includes(videoType ?? "") ? itemCount : undefined,
      channel: channel,
      hook_archetype: hookArchetype,
      pre_research: preResearch.trim() || undefined,
      additional_instructions: additionalInstructions.trim() || undefined,
      sample_script: sampleScript.trim() || undefined,
      // Pipeline-only options: the /scripts route ignores them, so only send
      // when the full-pipeline button kicked off the run.
      ...(mode === "pipeline"
        ? {
            visual_provider: visualProvider,
            ken_burns: kenBurns,
            render_section_cards: sectionCards,
            render_section_transitions: sectionTransitions,
            background_music: music,
            music_volume: musicVolume,
          }
        : {}),
    };

    try {
      const resp =
        mode === "pipeline" ? await createPipeline(body) : await createScript(body);

      setRun({
        projectSlug: resp.project_slug,
        logs: [],
        stageEvents: [],
        status: "running",
        mode,
      });

      // Backend may have renamed a legacy draft slug to a topic-derived one.
      // If the form was mounted from /projects/[draft-slug], navigate to the
      // new URL so the user lands on the renamed project. router.replace (not
      // push) — the draft URL isn't worth keeping in history.
      //
      // NOTE: This unmounts ScriptCreationForm on the per-project page (the
      // route segment changes), so the in-flight run state here is lost.
      // That's acceptable — Fix 2 (RunPanel hydration) plus the page's own
      // re-render against the new slug recover the streaming progress
      // immediately. On /projects/new there's no [slug] segment yet, so the
      // form stays mounted and onRunComplete handles navigation on done.
      if (projectSlug && resp.project_slug !== projectSlug) {
        router.replace(`/projects/${resp.project_slug}`);
      }

      cleanupRef.current = streamTaskLogs(
        resp.task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => {
          setRun((prev) => (prev ? { ...prev, status } : prev));
          if (status === "completed") {
            // Belt-and-braces: parent handler may call router.refresh(), but
            // also invalidate the TanStack cache so any client component
            // reading via useProjectQuery / useScenesQuery picks up changes.
            invalidateForProject(queryClient, resp.project_slug, router);
          }
          if (status === "completed" || status === "failed") {
            onRunComplete?.(resp.project_slug, status);
          }
        },
        undefined,
        (stageName, stageStatus) =>
          setRun((prev) =>
            prev
              ? {
                  ...prev,
                  stageEvents: [
                    ...prev.stageEvents,
                    { type: "stage", stage: stageName, status: stageStatus },
                  ],
                }
              : prev,
          ),
      );
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5">
      <Row label="Title" hint={`${topic.length} / 200`}>
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value.slice(0, 200))}
          placeholder="Enter your video title..."
          className="form-input"
          disabled={submitting}
        />
      </Row>

      <div className="grid gap-5 sm:grid-cols-2">
        <Row label="Video type" hint="Structure module">
          <VideoTypeSelect
            value={videoType}
            onChange={setVideoType}
            disabled={submitting}
          />
        </Row>

        <Row label="Channel" hint="Channel preset">
          <ChannelSelect value={channel} onChange={setChannel} disabled={submitting} />
        </Row>
      </div>

      <Row label="Hook archetype" hint="Opening structure">
        <HookArchetypeSelect
          value={hookArchetype}
          onChange={setHookArchetype}
          disabled={submitting}
        />
      </Row>

      {LIST_TYPES.includes(videoType ?? "") && (
        <Row
          label="Number of items"
          hint={`~${itemCount * 250 + 450} words total`}
        >
          <input
            type="number"
            min={3}
            max={12}
            value={itemCount}
            onChange={(e) =>
              setItemCount(
                Math.max(3, Math.min(12, Number(e.target.value) || 5)),
              )
            }
            disabled={submitting}
            className="form-input"
          />
        </Row>
      )}

      <Row
        label="Target length"
        hint={`~${targetMinutes * 150} words at 150 wpm`}
      >
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={3}
            max={30}
            value={targetMinutes}
            onChange={(e) => setTargetMinutes(Number(e.target.value))}
            disabled={submitting}
            className="flex-1 accent-accent"
          />
          <span className="w-16 text-right text-sm font-medium tabular-nums text-foreground">
            {targetMinutes} min
          </span>
        </div>
      </Row>

      <Row
        label="Pre-research notes"
        optional
        hint={
          preResearch.trim()
            ? `${preResearch.trim().split(/\s+/).filter(Boolean).length} words — GPT-5 will use these as a starting point`
            : "Empty = GPT-5 picks the angle on its own"
        }
      >
        <textarea
          value={preResearch}
          onChange={(e) => setPreResearch(e.target.value)}
          rows={6}
          placeholder="Notes, a list, or context for GPT-5 to build the research on."
          className="form-input font-mono text-xs"
          disabled={submitting}
        />
      </Row>

      <Row label="Additional instructions" optional>
        <textarea
          value={additionalInstructions}
          onChange={(e) => setAdditionalInstructions(e.target.value)}
          rows={2}
          placeholder="e.g. Keep tone respectful toward beginner gardeners"
          className="form-input"
          disabled={submitting}
        />
      </Row>

      <Row label="Sample script" optional hint="Style reference">
        <textarea
          value={sampleScript}
          onChange={(e) => setSampleScript(e.target.value)}
          rows={3}
          placeholder="Paste a successful script — the writer will match its rhythm and pacing without copying its structure or topic."
          className="form-input font-mono text-xs"
          disabled={submitting}
        />
      </Row>

      {/* Collapsed by default; these knobs only apply when the run starts via
          the "Run full pipeline" button (the /scripts route ignores them). */}
      <details className="overflow-hidden rounded-lg border border-border bg-background">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground hover:bg-surface-2">
          Full pipeline options
          <span className="ml-2 text-xs font-normal text-muted">
            Only applies to “Run full pipeline”
          </span>
        </summary>
        <div className="space-y-5 border-t border-border p-4">
          <Row label="Visual provider" hint="One provider for every scene">
            <div>
              <select
                value={visualProvider}
                onChange={(e) => setVisualProvider(e.target.value)}
                disabled={submitting || providers.length === 0}
                className="form-input"
              >
                {providers.length === 0 && <option>Loading...</option>}
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              {providersError && (
                <p className="mt-1 text-xs text-danger">{providersError}</p>
              )}
            </div>
          </Row>
          <RenderConfigPanel
            sectionTransitions={sectionTransitions}
            setSectionTransitions={setSectionTransitions}
            sectionCards={sectionCards}
            setSectionCards={setSectionCards}
            kenBurns={kenBurns}
            setKenBurns={setKenBurns}
            music={music}
            setMusic={setMusic}
            musicVolume={musicVolume}
            setMusicVolume={setMusicVolume}
          />
        </div>
      </details>

      {submitError && (
        <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {submitError}
        </div>
      )}

      <div className="flex flex-col-reverse gap-3 sm:flex-row">
        <button
          type="button"
          onClick={() => onRun("script")}
          disabled={!canSubmit}
          className="flex-1 rounded-md border border-border bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting && run?.mode === "script"
            ? "Starting..."
            : "Generate script only"}
        </button>
        <button
          type="button"
          onClick={() => onRun("pipeline")}
          disabled={!canSubmit}
          className="flex-1 rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
        >
          {submitting && run?.mode === "pipeline"
            ? "Starting..."
            : "Run full pipeline →"}
        </button>
      </div>

      {run && <RunLog run={run} />}

      <style>{`
        .form-input {
          width: 100%;
          padding: 0.5rem 0.75rem;
          background: var(--surface-2);
          color: var(--foreground);
          border: 1px solid var(--border);
          border-radius: 0.375rem;
          font-size: 0.875rem;
          outline: none;
          transition: border-color 0.15s;
        }
        .form-input:focus { border-color: var(--accent); }
        .form-input:disabled { opacity: 0.6; cursor: not-allowed; }
      `}</style>
    </div>
  );
}

function Row({
  label,
  hint,
  optional,
  placeholder,
  children,
}: {
  label: string;
  hint?: string;
  optional?: boolean;
  placeholder?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${placeholder ? "opacity-70" : ""}`}>
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">
          {label}
          {optional && (
            <span className="ml-1.5 text-xs font-normal text-muted">
              (optional)
            </span>
          )}
        </label>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function RunLog({
  run,
}: {
  run: {
    projectSlug: string;
    logs: string[];
    stageEvents: StageEvent[];
    status: TaskStatus;
    mode: "script" | "pipeline";
  };
}) {
  const stages = run.mode === "pipeline" ? PIPELINE_STAGES : SCRIPT_STAGES;
  const terminalStatus =
    run.status === "completed" || run.status === "failed" ? run.status : null;
  return (
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
            ? run.mode === "pipeline"
              ? "Running full pipeline..."
              : "Generating script..."
            : run.status === "completed"
              ? "Done"
              : run.status === "failed"
                ? "Failed"
                : "Queued"}
        </span>
      </div>
      <div className="border-b border-border px-4 py-3">
        <StageList
          stages={stages}
          events={run.stageEvents}
          terminalStatus={terminalStatus}
        />
      </div>
      <details>
        <summary className="cursor-pointer px-4 py-2 text-xs text-muted hover:text-muted-strong">
          Raw logs ({run.logs.length})
        </summary>
        <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
          {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
        </pre>
      </details>
    </div>
  );
}
