"use client";

import { useState } from "react";
import { cancelTask } from "@/lib/api";

type Props = {
  taskId: string;
  onCancelled?: () => void;
};

export function CancelTaskButton({ taskId, onCancelled }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doCancel() {
    setError(null);
    setPending(true);
    try {
      await cancelTask(taskId);
      onCancelled?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
      setConfirming(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-muted-strong hover:bg-surface-3"
      >
        Cancel
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-danger">{error}</span>}
      <button
        type="button"
        onClick={doCancel}
        disabled={pending}
        className="rounded-md bg-danger px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
      >
        {pending ? "Cancelling..." : "Confirm cancel"}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        disabled={pending}
        className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-muted-strong hover:bg-surface-2"
      >
        Keep running
      </button>
    </div>
  );
}
