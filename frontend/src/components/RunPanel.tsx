"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { streamTaskLogs, type TaskStatus } from "@/lib/api";

type RunState = {
  taskId: string;
  projectSlug: string;
  logs: string[];
  status: TaskStatus;
};

export type StartFn = () => Promise<{ task_id: string; project_slug: string }>;

type Props = {
  start: StartFn;
  buttonLabel: string;
  runningLabel?: string;
  completedLabel?: string;
  failedLabel?: string;
  disabled?: boolean;
  /** What to show as the "next step" link when the run completes. If omitted,
   *  a Refresh button is shown that re-fetches the server-rendered tree. */
  nextHref?: (slug: string) => string;
  nextLabel?: string;
};

export function RunPanel({
  start,
  buttonLabel,
  runningLabel = "Running...",
  completedLabel = "Done",
  failedLabel = "Failed",
  disabled = false,
  nextHref,
  nextLabel = "Next →",
}: Props) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  const isRunning = run?.status === "running" || submitting;

  async function onStart() {
    setSubmitError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      const { task_id, project_slug } = await start();
      const initialRun: RunState = {
        taskId: task_id,
        projectSlug: project_slug,
        logs: [],
        status: "running",
      };
      setRun(initialRun);

      cleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) =>
          setRun((prev) => (prev ? { ...prev, status } : prev)),
      );
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={onStart}
        disabled={disabled || isRunning}
        className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
      >
        {isRunning ? runningLabel : buttonLabel}
      </button>

      {submitError && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {submitError}
        </div>
      )}

      {run && (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <div className="flex items-center gap-3">
              <StatusDot status={run.status} />
              <div>
                <p className="text-sm font-medium text-foreground">
                  {run.status === "running"
                    ? runningLabel
                    : run.status === "completed"
                      ? completedLabel
                      : run.status === "failed"
                        ? failedLabel
                        : "Queued"}
                </p>
                <p className="font-mono text-xs text-muted">{run.projectSlug}</p>
              </div>
            </div>
            {run.status === "completed" && nextHref ? (
              <a
                href={nextHref(run.projectSlug)}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
              >
                {nextLabel}
              </a>
            ) : run.status === "completed" ? (
              <button
                type="button"
                onClick={() => router.refresh()}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
              >
                Refresh →
              </button>
            ) : null}
          </div>
          <pre className="max-h-96 overflow-auto bg-background px-5 py-3 font-mono text-xs leading-relaxed text-muted-strong">
            {run.logs.length === 0 ? "Waiting for output..." : run.logs.join("\n")}
          </pre>
        </div>
      )}
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
