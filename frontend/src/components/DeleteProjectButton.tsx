"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProject } from "@/lib/api";

export function DeleteProjectButton({
  slug,
  title,
}: {
  slug: string;
  title: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onConfirm() {
    setError(null);
    setPending(true);
    try {
      await deleteProject(slug);
      router.push("/projects");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPending(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted">Delete &quot;{title}&quot;?</span>
        <button
          type="button"
          onClick={onConfirm}
          disabled={pending}
          className="rounded-md bg-danger px-3 py-1 text-xs font-medium text-white hover:bg-danger/90 disabled:opacity-50"
        >
          {pending ? "Deleting..." : "Yes, delete"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          disabled={pending}
          className="rounded-md border border-border bg-surface px-3 py-1 text-xs text-muted-strong hover:bg-surface-2"
        >
          Cancel
        </button>
        {error && <span className="ml-2 text-xs text-danger">{error}</span>}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-muted-strong hover:border-danger/40 hover:bg-danger/10 hover:text-danger"
      title="Delete project"
    >
      Delete
    </button>
  );
}
