"use client";

import type { VisualMode, VisualProvider } from "@/lib/api";

/**
 * Four small icon buttons (one per visual mode). Active mode is highlighted;
 * modes whose providers are all unavailable are disabled. Icon set is inline
 * SVG — keeps us free of an icon dependency and matches the dark theme.
 *
 * `availableModes` is precomputed by the parent (it knows the full provider
 * registry) so this component stays dumb about how availability is derived.
 */
type Props = {
  modes: VisualMode[];
  providers: VisualProvider[];
  value: string;
  onChange: (mode: string) => void;
  disabled?: boolean;
};

export function ModeButtonGroup({
  modes,
  providers,
  value,
  onChange,
  disabled,
}: Props) {
  return (
    <div className="flex gap-1">
      {modes.map((mode) => {
        const hasAvailableProvider = providers.some(
          (p) => p.mode === mode.id && p.available,
        );
        const isActive = value === mode.id;
        const isDisabled = disabled || !hasAvailableProvider;
        return (
          <button
            key={mode.id}
            type="button"
            title={mode.label}
            aria-label={mode.label}
            aria-pressed={isActive}
            disabled={isDisabled}
            onClick={() => onChange(mode.id)}
            className={`flex h-8 w-8 items-center justify-center rounded-md border text-foreground transition-colors ${
              isActive
                ? "border-accent bg-accent/15 text-accent"
                : "border-border bg-surface-2 hover:bg-surface-3"
            } ${isDisabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"}`}
          >
            <ModeIcon mode={mode.id} />
          </button>
        );
      })}
    </div>
  );
}

function ModeIcon({ mode }: { mode: string }) {
  // 14px square inline SVGs. currentColor so the parent's active/disabled
  // colors carry through.
  switch (mode) {
    case "ai_image":
      return (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-3.5 w-3.5"
        >
          <rect x="2" y="2" width="12" height="12" rx="1.5" />
          <circle cx="6" cy="6" r="1.25" fill="currentColor" stroke="none" />
          <path d="M2.5 12 6 8.5 9 11l2.5-2.5L14 11" strokeLinejoin="round" />
          <path d="M11 3l1 1.5L13.5 5 12 5.5 11 7l-1-1.5L8.5 5 10 4.5z" />
        </svg>
      );
    case "ai_video":
      return (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-3.5 w-3.5"
        >
          <rect x="2" y="3" width="10" height="10" rx="1.5" />
          <path d="M12 7l2.5-1.5v5L12 9z" strokeLinejoin="round" />
          <path d="M5.5 6l1 1.5L8 8l-1.5.5L5.5 10 4.5 8.5 3 8l1.5-.5z" />
        </svg>
      );
    case "stock_image":
      return (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-3.5 w-3.5"
        >
          <rect x="2" y="2" width="12" height="12" rx="1.5" />
          <circle cx="6" cy="6" r="1.25" fill="currentColor" stroke="none" />
          <path d="M2.5 12 6 8.5 9 11l2.5-2.5L14 11" strokeLinejoin="round" />
        </svg>
      );
    case "stock_video":
      return (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-3.5 w-3.5"
        >
          <rect x="2" y="3" width="10" height="10" rx="1.5" />
          <path d="M12 7l2.5-1.5v5L12 9z" strokeLinejoin="round" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 16 16" className="h-3.5 w-3.5">
          <circle cx="8" cy="8" r="3" fill="currentColor" />
        </svg>
      );
  }
}
