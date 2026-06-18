"use client";

import { useEffect, useRef, useState } from "react";

import {
  createScript,
  createPipeline,
  streamTaskLogs,
  type ScriptRequest,
  type TaskStatus,
} from "@/lib/api";

import { VideoTypeSelect } from "@/components/VideoTypeSelect";

/**
 * Single canonical script-creation form used by both /create and
 * /projects/[slug] (when the project has no script yet). Fields here are the
 * per-video knobs that affect script generation; voice speed lives on the
 * Voiceover tab (channel preset will own its default once channels land).
 */
export type ScriptCreationFormProps = {
  /** When set, the script generates into this existing project slug.
   * When unset, the API derives a slug from the topic and may create a new project. */
  projectSlug?: string;
  /** Called when a run completes successfully with the resolved slug.
   * /create uses it to surface an "Open project →" link; /projects/[slug] uses it to refresh. */
  onRunComplete?: (projectSlug: string, status: TaskStatus) => void;
};

export function ScriptCreationForm({
  projectSlug,
  onRunComplete,
}: ScriptCreationFormProps) {
  const [topic, setTopic] = useState("");
  const [targetMinutes, setTargetMinutes] = useState(10);
  const [videoType, setVideoType] = useState<string | undefined>(undefined);
  const [preResearch, setPreResearch] = useState("");
  const [additionalInstructions, setAdditionalInstructions] = useState("");
  const [sampleScript, setSampleScript] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [run, setRun] = useState<{
    projectSlug: string;
    logs: string[];
    status: TaskStatus;
    mode: "script" | "pipeline";
  } | null>(null);

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
      pre_research: preResearch.trim() || undefined,
      additional_instructions: additionalInstructions.trim() || undefined,
      sample_script: sampleScript.trim() || undefined,
    };

    try {
      const resp =
        mode === "pipeline" ? await createPipeline(body) : await createScript(body);

      setRun({
        projectSlug: resp.project_slug,
        logs: [],
        status: "running",
        mode,
      });

      cleanupRef.current = streamTaskLogs(
        resp.task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => {
          setRun((prev) => (prev ? { ...prev, status } : prev));
          if (status === "completed" || status === "failed") {
            onRunComplete?.(resp.project_slug, status);
          }
        },
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

        <Row label="Channel" hint="Presets coming" placeholder>
          <select className="form-input" disabled value="default">
            <option value="default">Default</option>
          </select>
        </Row>
      </div>

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
          placeholder="Paste a successful script (saved, prompt-wiring TBD)..."
          className="form-input font-mono text-xs"
          disabled={submitting}
        />
      </Row>

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
    status: TaskStatus;
    mode: "script" | "pipeline";
  };
}) {
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
      <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
        {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
      </pre>
    </div>
  );
}
