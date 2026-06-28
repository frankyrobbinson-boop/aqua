"use client";

import { useState } from "react";

type Props = {
  path: string;
  label?: string;
};

export function CopyPathButton({ path, label = "Copy path" }: Props) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API may be unavailable (insecure context). Fall back to a
      // selection so the user can copy manually.
      window.prompt("Copy this path:", path);
    }
  }

  return (
    <button
      type="button"
      onClick={onCopy}
      className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-3"
    >
      {copied ? "Path copied" : label}
    </button>
  );
}
