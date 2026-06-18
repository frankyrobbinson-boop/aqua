"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  createPipeline,
  startVoiceover,
  startVisuals,
  startRender,
  streamTaskLogs,
  getProject,
  getScenes,
  type TaskStatus,
  type ScriptRequest,
} from "@/lib/api";
import { ScriptCreationForm } from "@/components/ScriptCreationForm";
import { Stepper, type Step } from "@/components/Stepper";
import { PlaceholderRow } from "@/components/StagePanel";

// Modes that go through the per-page action buttons. Step 1 (script) is
// driven by ScriptCreationForm's own buttons.
type StageMode = "voiceover" | "visuals" | "render" | "pipeline";

type RunState = {
  taskId: string;
  projectSlug: string;
  logs: string[];
  status: TaskStatus;
  mode: StageMode;
};

type Completed = {
  script: boolean;
  voiceover: boolean;
  visuals: boolean;
  render: boolean;
};

const EMPTY_COMPLETED: Completed = {
  script: false,
  voiceover: false,
  visuals: false,
  render: false,
};

export default function CreatePage() {
  const [step, setStep] = useState<Step>(1);

  // Project state — set after the script run resolves a slug.
  const [projectSlug, setProjectSlug] = useState<string | null>(null);
  const [completed, setCompleted] = useState<Completed>(EMPTY_COMPLETED);

  // Voiceover, Visuals, Render placeholders — local-only knobs, not yet wired.
  const [voiceId, setVoiceId] = useState("");
  const [renderSubtitles, setRenderSubtitles] = useState(true);
  const [renderMusic, setRenderMusic] = useState(false);

  // Run state for steps 2–4 + full pipeline. Step 1 has its own run state
  // inside ScriptCreationForm.
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  async function refreshCompletion(slug: string) {
    try {
      const [proj, scenes] = await Promise.all([
        getProject(slug),
        getScenes(slug),
      ]);
      const withFootage = scenes.filter((s) => s.has_footage).length;
      setCompleted({
        script: proj.has_script,
        voiceover: proj.has_audio,
        visuals: scenes.length > 0 && withFootage === scenes.length,
        render: proj.has_video,
      });
    } catch {
      // project doesn't exist yet — leave completion state alone
    }
  }

  const isRunning = submitting || run?.status === "running";

  function canRunStage(mode: StageMode): boolean {
    if (isRunning) return false;
    if (!projectSlug) return false;
    switch (mode) {
      case "voiceover":
        return completed.script;
      case "visuals":
        return completed.voiceover;
      case "render":
        return completed.visuals;
      case "pipeline":
        return true;
    }
  }

  async function onRunStage(mode: StageMode) {
    if (!canRunStage(mode) || !projectSlug) return;
    setSubmitError(null);
    setSubmitting(true);
    cleanupRef.current?.();

    try {
      let resp: { task_id: string; project_slug: string };
      switch (mode) {
        case "voiceover":
          resp = await startVoiceover(projectSlug);
          break;
        case "visuals":
          resp = await startVisuals(projectSlug);
          break;
        case "render":
          resp = await startRender(projectSlug);
          break;
        case "pipeline": {
          // Re-running the pipeline from /create after the script exists.
          // ScriptRequest is used here to thread project_slug; topic carried
          // by the existing project.
          const body: ScriptRequest = {
            topic: "(resume pipeline)",
            target_minutes: 10,
            project_slug: projectSlug,
          };
          resp = await createPipeline(body);
          break;
        }
      }

      const initial: RunState = {
        taskId: resp.task_id,
        projectSlug: resp.project_slug,
        logs: [],
        status: "running",
        mode,
      };
      setRun(initial);

      cleanupRef.current = streamTaskLogs(
        resp.task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => {
          setRun((prev) => (prev ? { ...prev, status } : prev));
          if (status === "completed") refreshCompletion(resp.project_slug);
        },
      );
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const completedSet = new Set<Step>();
  if (completed.script) completedSet.add(1);
  if (completed.voiceover) completedSet.add(2);
  if (completed.visuals) completedSet.add(3);
  if (completed.render) completedSet.add(4);

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Stepper
        current={step}
        completed={completedSet}
        onSelect={(n) => setStep(n)}
      />

      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Create video
        </h1>
        <p className="mt-1 text-sm text-muted">
          Configure each stage, then generate the script alone or run the full
          pipeline.
        </p>
      </div>

      <section className="rounded-xl border border-border bg-surface p-6">
        {step === 1 && (
          <ScriptCreationForm
            projectSlug={projectSlug ?? undefined}
            onRunComplete={(slug, status) => {
              setProjectSlug(slug);
              if (status === "completed") refreshCompletion(slug);
            }}
          />
        )}
        {step === 2 && (
          <VoiceoverStage voiceId={voiceId} setVoiceId={setVoiceId} />
        )}
        {step === 3 && <VisualsStage />}
        {step === 4 && (
          <RenderStage
            renderSubtitles={renderSubtitles}
            setRenderSubtitles={setRenderSubtitles}
            renderMusic={renderMusic}
            setRenderMusic={setRenderMusic}
          />
        )}
      </section>

      {step === 1 && projectSlug && completed.script && (
        <div className="mt-4 flex justify-end">
          <Link
            href={`/projects/${projectSlug}`}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Open project →
          </Link>
        </div>
      )}

      {submitError && (
        <div className="mt-6 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {submitError}
        </div>
      )}

      {step !== 1 && (
        <StageActions
          step={step}
          canRun={canRunStage}
          onRun={onRunStage}
          runningMode={isRunning ? run?.mode : undefined}
        />
      )}

      {run && <RunPanelInline run={run} />}

      <style>{`
        .input {
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
        .input:focus {
          border-color: var(--accent);
        }
        .input:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action buttons (stages 2–4 + full pipeline)
// ---------------------------------------------------------------------------

const STAGE_BUTTONS: Record<
  Exclude<Step, 1>,
  { mode: StageMode; idleLabel: string; activeLabel: string }
> = {
  2: {
    mode: "voiceover",
    idleLabel: "Generate voiceover only",
    activeLabel: "Generating voiceover...",
  },
  3: {
    mode: "visuals",
    idleLabel: "Generate visuals only",
    activeLabel: "Fetching visuals...",
  },
  4: {
    mode: "render",
    idleLabel: "Render video only",
    activeLabel: "Rendering...",
  },
};

function StageActions({
  step,
  canRun,
  onRun,
  runningMode,
}: {
  step: Step;
  canRun: (mode: StageMode) => boolean;
  onRun: (mode: StageMode) => void;
  runningMode: StageMode | undefined;
}) {
  if (step === 1) return null;
  const cfg = STAGE_BUTTONS[step];
  const stageEnabled = canRun(cfg.mode);
  const pipelineEnabled = canRun("pipeline");
  const stageRunning = runningMode === cfg.mode;
  const pipelineRunning = runningMode === "pipeline";

  return (
    <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row">
      <button
        type="button"
        onClick={() => onRun(cfg.mode)}
        disabled={!stageEnabled}
        className="flex-1 rounded-md border border-border bg-surface px-4 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {stageRunning ? cfg.activeLabel : cfg.idleLabel}
      </button>
      <button
        type="button"
        onClick={() => onRun("pipeline")}
        disabled={!pipelineEnabled}
        className="flex-1 rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
      >
        {pipelineRunning ? "Running pipeline..." : "Run full pipeline →"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Voiceover (placeholders)
// ---------------------------------------------------------------------------

function VoiceoverStage({
  voiceId,
  setVoiceId,
}: {
  voiceId: string;
  setVoiceId: (s: string) => void;
}) {
  return (
    <div className="space-y-5">
      <StageHeader
        title="Voiceover"
        subtitle="ElevenLabs · model, voice, speed"
        badge="placeholders"
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <PlaceholderRow label="Provider" hint="More coming">
          <select className="input" disabled value="elevenlabs">
            <option value="elevenlabs">ElevenLabs</option>
          </select>
        </PlaceholderRow>

        <PlaceholderRow label="Model" hint="Coming">
          <select className="input" disabled value="multilingual-v2">
            <option>Multilingual v2</option>
          </select>
        </PlaceholderRow>
      </div>

      <PlaceholderRow
        label="Voice"
        hint={voiceId ? "Will override .env when wired" : "Inherits from .env"}
      >
        <input
          value={voiceId}
          onChange={(e) => setVoiceId(e.target.value)}
          placeholder="Paste an ElevenLabs voice ID..."
          className="input font-mono text-xs"
          disabled
        />
      </PlaceholderRow>

      <PlaceholderRow label="Speed" hint="Set on the project's Voiceover tab">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0.8}
            max={1.2}
            step={0.05}
            value={1.0}
            disabled
            readOnly
            className="flex-1 accent-accent"
          />
          <span className="w-16 text-right text-sm tabular-nums text-muted">
            1.0x
          </span>
        </div>
      </PlaceholderRow>

      <InfoBox>
        <strong className="text-foreground">Already on:</strong> loudness
        normalization (−16 LUFS), chunk stitching for prosody continuity.
      </InfoBox>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Visuals (placeholders)
// ---------------------------------------------------------------------------

function VisualsStage() {
  return (
    <div className="space-y-5">
      <StageHeader
        title="Visuals"
        subtitle="Stock footage · AI generation (later)"
        badge="placeholders"
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <PlaceholderRow label="Provider" hint="Stock only for now">
          <select className="input" disabled value="pexels">
            <option value="pexels">Pexels (stock)</option>
          </select>
        </PlaceholderRow>

        <PlaceholderRow label="AI fallback" hint="Coming">
          <select className="input" disabled value="none">
            <option value="none">None — stock only</option>
          </select>
        </PlaceholderRow>
      </div>

      <PlaceholderRow label="Scene granularity" hint="8–15s default">
        <select className="input" disabled value="default">
          <option value="default">Default (40–60 scenes per 10 min)</option>
        </select>
      </PlaceholderRow>

      <InfoBox>
        <strong className="text-foreground">Already on:</strong> Claude Haiku LLM
        rerank · respects Pexels relevance order · topic-anchored search queries.
      </InfoBox>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Render (placeholders)
// ---------------------------------------------------------------------------

function RenderStage({
  renderSubtitles,
  setRenderSubtitles,
  renderMusic,
  setRenderMusic,
}: {
  renderSubtitles: boolean;
  setRenderSubtitles: (b: boolean) => void;
  renderMusic: boolean;
  setRenderMusic: (b: boolean) => void;
}) {
  return (
    <div className="space-y-5">
      <StageHeader
        title="Render"
        subtitle="Resolution · fps · overlays · music"
        badge="placeholders"
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <PlaceholderRow label="Resolution" hint="1080p locked">
          <div className="flex gap-1">
            {["720p", "1080p"].map((r) => (
              <button
                key={r}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  r === "1080p"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </PlaceholderRow>

        <PlaceholderRow label="Frame rate" hint="25 fps locked">
          <div className="flex gap-1">
            {["24", "25", "30"].map((f) => (
              <button
                key={f}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  f === "25"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {f} fps
              </button>
            ))}
          </div>
        </PlaceholderRow>
      </div>

      <ToggleRow
        label="Subtitles"
        checked={renderSubtitles}
        onChange={setRenderSubtitles}
        hint="Word-level highlight, burned in"
        placeholder
      />
      <ToggleRow
        label="Background music"
        checked={renderMusic}
        onChange={setRenderMusic}
        hint="Upload + ducking — coming"
        placeholder
      />

      <PlaceholderRow label="Scene transition" hint="Hard cuts">
        <select className="input" disabled value="cut">
          <option value="cut">Hard cut</option>
        </select>
      </PlaceholderRow>

      <InfoBox>
        <strong className="text-foreground">Render pipeline:</strong> libx264 ·
        CRF 18 · scale+crop to fit · libass subtitle burn-in · AAC audio mux.
      </InfoBox>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

function StageHeader({
  title,
  subtitle,
  badge,
}: {
  title: string;
  subtitle: string;
  badge?: string;
}) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        <p className="text-xs text-muted">{subtitle}</p>
      </div>
      {badge && (
        <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs text-muted">
          {badge}
        </span>
      )}
    </div>
  );
}

function InfoBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 p-3 text-xs text-muted">
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
  hint,
  placeholder = false,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: string;
  placeholder?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${
        placeholder ? "opacity-70" : ""
      }`}
    >
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        {hint && <p className="text-xs text-muted">{hint}</p>}
      </div>
      <button
        type="button"
        onClick={() => !placeholder && onChange(!checked)}
        disabled={placeholder}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-surface-3"
        } ${placeholder ? "cursor-not-allowed" : ""}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

function RunPanelInline({ run }: { run: RunState }) {
  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-3">
          <StatusDot status={run.status} />
          <div>
            <p className="text-sm font-medium text-foreground">
              {labelFor(run.status, run.mode)}
            </p>
            <p className="font-mono text-xs text-muted">{run.projectSlug}</p>
          </div>
        </div>
        {run.status === "completed" && (
          <Link
            href={`/projects/${run.projectSlug}`}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
          >
            Open project →
          </Link>
        )}
      </div>
      <pre className="max-h-[28rem] overflow-auto bg-background px-5 py-3 font-mono text-xs leading-relaxed text-muted-strong">
        {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
      </pre>
    </div>
  );
}

function StatusDot({ status }: { status: TaskStatus }) {
  const cls =
    status === "completed"
      ? "bg-success"
      : status === "failed"
        ? "bg-danger"
        : status === "running"
          ? "bg-accent animate-pulse"
          : "bg-muted";
  return <span className={`h-2.5 w-2.5 rounded-full ${cls}`} />;
}

function labelFor(status: TaskStatus, mode: StageMode): string {
  const noun: Record<StageMode, string> = {
    voiceover: "Voiceover",
    visuals: "Visuals",
    render: "Render",
    pipeline: "Pipeline",
  };
  if (status === "completed") return `${noun[mode]} complete`;
  if (status === "failed") return `${noun[mode]} failed`;
  if (status === "running") {
    return mode === "pipeline"
      ? "Running pipeline (script → audio → visuals → render)..."
      : `Generating ${noun[mode].toLowerCase()}...`;
  }
  return "Queued";
}
