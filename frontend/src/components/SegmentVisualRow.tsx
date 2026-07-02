"use client";

import { useState } from "react";
import { ModeButtonGroup } from "./ModeButtonGroup";
import { ProviderDropdown } from "./ProviderDropdown";
import type {
  VisualMode,
  VisualProvider,
  VisualSegmentConfig,
} from "@/lib/api";

/**
 * One configuration row per segment: scene count input, mode buttons, provider
 * dropdown, settings cog (placeholder), remove (placeholder).
 *
 * Mutations bubble up via `onChange` — the parent owns the full segments[]
 * array and persists it. Local state is limited to the transient cog popover.
 */
type Props = {
  segment: VisualSegmentConfig;
  label: string;
  timeRange: { start: number; end: number } | null;
  modes: VisualMode[];
  providers: VisualProvider[];
  onChange: (next: VisualSegmentConfig) => void;
  disabled?: boolean;
};

export function SegmentVisualRow({
  segment,
  label,
  timeRange,
  modes,
  providers,
  onChange,
  disabled,
}: Props) {
  const [showCog, setShowCog] = useState(false);

  const duration =
    timeRange && timeRange.end > timeRange.start
      ? timeRange.end - timeRange.start
      : null;
  const avg =
    duration && segment.scene_count != null && segment.scene_count > 0
      ? duration / segment.scene_count
      : null;

  const isMixed = segment.mode === "mixed";

  function handleModeChange(nextMode: string) {
    if (nextMode === segment.mode) return;
    // "mixed" has no provider of its own (routing is per scene). Keep the
    // existing provider value dormant rather than snapping to a non-existent
    // mixed provider, which would blank the field.
    if (nextMode === "mixed") {
      onChange({ ...segment, mode: nextMode });
      return;
    }
    // When the user switches mode, the existing provider may not handle the
    // new mode. Snap to the first available provider for the new mode; fall
    // back to the first listed (even if unavailable) so the select isn't
    // blank.
    const candidates = providers.filter((p) => p.mode === nextMode);
    const nextProvider =
      candidates.find((p) => p.available)?.id ??
      candidates[0]?.id ??
      segment.provider;
    onChange({ ...segment, mode: nextMode, provider: nextProvider });
  }

  return (
    <div className="rounded-lg border border-border bg-surface-2 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="font-mono text-xs text-muted">
            {timeRange
              ? `${fmt(timeRange.start)} — ${fmt(timeRange.end)}`
              : "Timing not available"}
          </p>
        </div>
        <button
          type="button"
          aria-label="Remove segment (placeholder)"
          title="Segments come from the scene plan and can't be removed yet."
          disabled
          className="rounded-md p-1.5 text-muted opacity-40 hover:bg-surface-3"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="h-3.5 w-3.5"
          >
            <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-[auto_auto_1fr_auto] sm:items-end">
        {/* Scene count */}
        <div>
          <label className="mb-1 block text-xs text-muted">Scenes</label>
          {segment.scene_count != null ? (
            <>
              <div className="flex items-center gap-1.5">
                <svg
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="h-3.5 w-3.5 text-muted"
                >
                  <circle cx="8" cy="8" r="6" />
                  <path d="M8 5v3.5l2 1.5" strokeLinecap="round" />
                </svg>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={segment.scene_count}
                  disabled={disabled}
                  onChange={(e) => {
                    const n = Math.max(
                      1,
                      Math.min(50, Number(e.target.value) || 1),
                    );
                    onChange({ ...segment, scene_count: n });
                  }}
                  className="w-16 rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-foreground outline-none focus:border-accent"
                />
              </div>
              <p className="mt-1 text-[10px] text-muted">
                {avg
                  ? `every ${avg.toFixed(1)}s · max ${Math.ceil(avg * 1.5)}s`
                  : "—"}
              </p>
            </>
          ) : (
            <p className="text-[10px] text-muted">set when you generate</p>
          )}
        </div>

        {/* Mode buttons */}
        <div>
          <label className="mb-1 block text-xs text-muted">Mode</label>
          <ModeButtonGroup
            modes={modes}
            providers={providers}
            value={segment.mode}
            onChange={handleModeChange}
            disabled={disabled}
          />
        </div>

        {/* Provider dropdown */}
        <div className="relative">
          <label className="mb-1 block text-xs text-muted">Provider</label>
          <div className="flex items-center gap-2">
            {isMixed ? (
              <span className="rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-muted">
                Routed per scene
              </span>
            ) : (
              <ProviderDropdown
                providers={providers}
                mode={segment.mode}
                value={segment.provider}
                onChange={(p) => onChange({ ...segment, provider: p })}
                disabled={disabled}
              />
            )}
            <button
              type="button"
              aria-label="Per-segment style settings"
              onClick={() => setShowCog((v) => !v)}
              className="rounded-md border border-border bg-surface px-1.5 py-1.5 text-muted hover:bg-surface-3"
            >
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className="h-3.5 w-3.5"
              >
                <circle cx="8" cy="8" r="2" />
                <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5L13 13M3 13l1.5-1.5M11.5 4.5L13 3" />
              </svg>
            </button>
          </div>
          {showCog && (
            <div className="absolute right-0 top-full z-10 mt-1 w-56 rounded-md border border-border bg-surface p-2 text-xs text-muted shadow-lg">
              Per-segment style settings — coming soon.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}
