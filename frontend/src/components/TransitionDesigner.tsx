"use client";

import dynamic from "next/dynamic";
import { Component, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ColorField } from "@/components/ColorField";
import {
  deleteTransitionDesign,
  getTransitionDesigns,
  remotionOutUrl,
  renderTransitionPreview,
  saveTransitionDesign,
  streamTaskLogs,
  type TaskStatus,
  type TransitionDesign,
  type TransitionLibrary,
} from "@/lib/api";
import { FPS, HEIGHT, WIDTH } from "@/remotion/constants";
import {
  getTransition,
  TRANSITIONS,
  type TransitionParams,
  type TransitionTimingId,
} from "@/remotion/transitions/registry";
import {
  previewDurationInFrames,
  TransitionPreview,
} from "@/remotion/transitions/TransitionPreview";

// The Player touches browser-only APIs, so it must never render on the server.
// next/dynamic with ssr:false keeps it out of the SSR pass. The cast restores
// the generic Player type (erased by dynamic's loader). `typeof import(...)` is
// a type-only query — erased at compile time, no runtime import.
const Player = dynamic(
  () => import("@remotion/player").then((m) => m.Player),
  { ssr: false },
) as unknown as typeof import("@remotion/player").Player;

const FIELD_CLASS =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent";

const TIMING_OPTIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "linear", label: "Linear" },
  { id: "spring", label: "Spring" },
];

// Transition-length bounds (frames). The preview derives each clip's length from
// this (clip = duration + hold), so every value in range is safe — the two-clip
// stage always has real content on both sides of the overlap.
const DURATION_MIN = 6;
const DURATION_MAX = 60;

// Format a numeric-knob value for its readout: 2 decimals for sub-integer steps
// (rotation, strength…), whole numbers otherwise (angle, amplitude…).
function formatKnob(value: number, step: number): string {
  return step < 1 ? value.toFixed(2) : String(Math.round(value));
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block text-xs font-medium text-muted-strong"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function Select({
  id,
  value,
  onChange,
  options,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ id: string; label: string }>;
}) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${FIELD_CLASS} cursor-pointer`}
    >
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Safety net around the live <Player>: if a presentation throws while
 *  rendering in the browser, show a small placeholder instead of blanking the
 *  whole tab. Keyed to the selected type by the caller, so switching transitions
 *  resets a tripped boundary. */
class PreviewErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="flex items-center justify-center rounded-lg border border-border bg-background text-sm text-muted"
          style={{ aspectRatio: "16 / 9" }}
        >
          Preview unavailable
        </div>
      );
    }
    return this.props.children;
  }
}

/** In-flight render-preview state (Tier-B shaders), mirroring CardDesigner's
 *  RunState: the task id, its streamed log lines, live status, and the output
 *  filename for playback once complete. */
type PreviewRun = {
  taskId: string;
  logs: string[];
  status: TaskStatus;
  filename: string;
};

/**
 * Transitions designer: the transition-type picker, the controls (duration,
 * timing, direction when supported, plus per-transition knobs — flower edge
 * color, shader knobs), and the per-channel saved-design library.
 * The preview branches on the transition's tier: Tier A (CSS/SVG) previews live
 * in a looping <Player>; Tier B (WebGL shaders, which the browser can't run)
 * previews via a short MP4 render (POST /transitions/preview) with SSE logs.
 * Scoped to one `channel` (passed down from the workspace, which owns the
 * ChannelSelect).
 */
export function TransitionDesigner({
  channel,
}: {
  channel: string | undefined;
}) {
  const [type, setType] = useState<string>(TRANSITIONS[0].id);
  const [params, setParams] = useState<TransitionParams>(
    () => TRANSITIONS[0].defaultParams,
  );

  // Saved-design library, scoped to the selected channel + the "transition"
  // role. Its own error box (like CardDesigner) so a save/load failure never
  // masquerades as anything else.
  const [library, setLibrary] = useState<TransitionLibrary | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);

  // Render-preview (Tier-B shaders only): the in-flight run + its own error box,
  // kept separate from the library error. `submitting` covers the brief gap
  // before the task reports "running". `cleanupRef` holds the open SSE closer.
  const [previewRun, setPreviewRun] = useState<PreviewRun | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  const def = getTransition(type);

  // Close any open SSE stream on unmount.
  useEffect(() => () => cleanupRef.current?.(), []);

  // Drop any render-preview and close its open stream — the prior clip was for a
  // different transition. Called from every code path that changes `type` (the
  // picker + loading a saved design). A param tweak keeps the last clip until the
  // user re-renders on a fresh click, per the design.
  function resetPreview() {
    cleanupRef.current?.();
    cleanupRef.current = null;
    setPreviewRun(null);
    setPreviewError(null);
    setSubmitting(false);
  }

  // Load the selected channel's saved transition designs — on mount (once the
  // workspace's ChannelSelect auto-picks the default) and whenever it changes.
  useEffect(() => {
    if (!channel) return;
    let cancelled = false;
    getTransitionDesigns(channel)
      .then((lib) => {
        if (!cancelled) {
          setLibrary(lib);
          setLibraryError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLibrary(null);
          setLibraryError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [channel]);

  // Switching transitions reseeds the form with that transition's defaults, so
  // every controlled input stays defined and the knobs match the new type.
  function selectType(id: string) {
    setType(id);
    setParams(getTransition(id).defaultParams);
    resetPreview();
  }

  function update<K extends keyof TransitionParams>(
    key: K,
    value: TransitionParams[K],
  ) {
    setParams((prev) => ({ ...prev, [key]: value }));
  }

  // Save the current design as a named variant under the selected channel.
  async function onSaveDesign() {
    if (!channel) return;
    const raw = window.prompt("Save this transition as a design named:");
    if (raw === null) return; // dialog cancelled
    const name = raw.trim();
    if (!name) return;
    setLibraryError(null);
    try {
      setLibrary(await saveTransitionDesign(channel, name, type, params));
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : String(err));
    }
  }

  // Load a saved design: switch to its transition, then merge its params over
  // that transition's defaults so every controlled input stays defined.
  function onLoadDesign(design: TransitionDesign) {
    setType(design.card_id);
    setParams({
      ...getTransition(design.card_id).defaultParams,
      ...design.props,
    });
    resetPreview();
  }

  async function onDeleteDesign(name: string) {
    if (!channel) return;
    setLibraryError(null);
    try {
      setLibrary(await deleteTransitionDesign(channel, name));
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : String(err));
    }
  }

  // Render a short MP4 of the current Tier-B transition and stream its task log
  // (same flow as CardDesigner's Render-to-MP4). Only fires on an explicit click
  // — never auto-renders on a param change.
  async function onRenderPreview() {
    if (previewing) return;
    setPreviewError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      const { task_id, filename } = await renderTransitionPreview(type, params);
      setPreviewRun({ taskId: task_id, logs: [], status: "running", filename });
      cleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setPreviewRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => setPreviewRun((prev) => (prev ? { ...prev, status } : prev)),
        (err) => setPreviewError(err instanceof Error ? err.message : String(err)),
      );
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  // Two clips overlapped by the transition — the length the Player loops over.
  const previewFrames = previewDurationInFrames(params);
  const showEdgeColor = def.paramKeys.includes("edgeColor");
  const previewing = submitting || previewRun?.status === "running";
  const previewVideoUrl =
    previewRun?.status === "completed" ? remotionOutUrl(previewRun.filename) : null;

  return (
    <section className="space-y-6">
      {/* Transition picker */}
      <div className="flex flex-wrap gap-2">
        {TRANSITIONS.map((t) => {
          const active = t.id === type;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => selectType(t.id)}
              title={t.description}
              aria-pressed={active}
              className={`rounded-md border px-3.5 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border bg-surface text-muted hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        {/* Controls */}
        <div className="space-y-5 rounded-xl border border-border bg-surface p-5">
          <div className="space-y-2">
            <p className="text-xs text-muted">{def.description}</p>
            {def.tier === "B" && (
              <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-muted">
                shader · best in Chrome
              </span>
            )}
          </div>

          <Field label="Duration" htmlFor="transition-duration">
            <div className="flex items-center gap-3">
              <input
                id="transition-duration"
                type="range"
                min={DURATION_MIN}
                max={DURATION_MAX}
                step={1}
                value={params.durationInFrames}
                onChange={(e) =>
                  update("durationInFrames", Number(e.target.value))
                }
                className="flex-1 accent-accent"
              />
              <span className="w-24 text-right text-sm font-medium tabular-nums text-foreground">
                {params.durationInFrames}f ·{" "}
                {(params.durationInFrames / FPS).toFixed(2)}s
              </span>
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Timing" htmlFor="transition-timing">
              <Select
                id="transition-timing"
                value={params.timing}
                onChange={(v) => update("timing", v as TransitionTimingId)}
                options={TIMING_OPTIONS}
              />
            </Field>
            {def.supportsDirection && def.directionOptions ? (
              <Field label="Direction" htmlFor="transition-direction">
                <Select
                  id="transition-direction"
                  value={params.direction}
                  onChange={(v) => update("direction", v)}
                  options={def.directionOptions}
                />
              </Field>
            ) : (
              <div />
            )}
          </div>

          {showEdgeColor && (
            <Field label="Edge color">
              <ColorField
                value={params.edgeColor}
                onChange={(hex) => update("edgeColor", hex)}
              />
            </Field>
          )}

          {/* Per-shader numeric knobs (+ flowerSwipe angle) — a bounded slider
              per definition-declared param. */}
          {def.numericParams?.map((spec) => (
            <Field
              key={spec.key}
              label={spec.label}
              htmlFor={`transition-${spec.key}`}
            >
              <div className="flex items-center gap-3">
                <input
                  id={`transition-${spec.key}`}
                  type="range"
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  value={params[spec.key]}
                  onChange={(e) => update(spec.key, Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="w-14 text-right text-sm font-medium tabular-nums text-foreground">
                  {formatKnob(params[spec.key], spec.step)}
                </span>
              </div>
            </Field>
          ))}

          {/* Saved designs — per-channel transition library */}
          <div className="space-y-3 border-t border-border pt-5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-strong">
                Saved designs
              </span>
              <button
                type="button"
                onClick={onSaveDesign}
                disabled={!channel}
                className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Save as design
              </button>
            </div>

            {libraryError && (
              <div className="rounded-md border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
                {libraryError}
              </div>
            )}

            {library && library.presets.length === 0 && (
              <p className="text-xs text-muted">No saved designs yet.</p>
            )}

            {library && library.presets.length > 0 && (
              <ul className="space-y-1.5">
                {library.presets.map((design) => (
                  <li key={design.name} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onLoadDesign(design)}
                      className="flex flex-1 items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-surface-2"
                    >
                      <span className="truncate font-medium">
                        {design.name}
                      </span>
                      <span className="shrink-0 text-xs text-muted">
                        {getTransition(design.card_id).label}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteDesign(design.name)}
                      aria-label={`Delete design ${design.name}`}
                      className="shrink-0 rounded-md border border-border bg-surface px-2.5 py-2 text-sm leading-none text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Preview — Tier A previews live; Tier B (WebGL shaders the browser
            can't run) previews via a short MP4 render. */}
        <div className="space-y-4">
          {def.tier === "A" ? (
            // Boundary keyed to `type` so switching transitions resets a tripped
            // fallback and re-mounts a fresh Player.
            <PreviewErrorBoundary key={type}>
              <div className="overflow-hidden rounded-lg border border-border bg-background">
                <Player
                  key={type}
                  component={TransitionPreview}
                  inputProps={{ type, params }}
                  durationInFrames={previewFrames}
                  fps={FPS}
                  compositionWidth={WIDTH}
                  compositionHeight={HEIGHT}
                  style={{ width: "100%", aspectRatio: "16 / 9" }}
                  controls
                  autoPlay
                  loop
                />
              </div>
            </PreviewErrorBoundary>
          ) : (
            <div className="space-y-4 rounded-xl border border-border bg-surface p-5">
              <p className="text-xs text-muted">
                Shader transitions preview via a quick render (live browser
                preview isn&apos;t supported).
              </p>

              <button
                type="button"
                onClick={onRenderPreview}
                disabled={previewing}
                className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
              >
                {submitting
                  ? "Starting..."
                  : previewRun?.status === "running"
                    ? "Rendering..."
                    : "Render preview"}
              </button>

              {previewError && (
                <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
                  {previewError}
                </div>
              )}

              {previewRun && (
                <div className="overflow-hidden rounded-lg border border-border bg-background">
                  <div className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        previewRun.status === "completed"
                          ? "bg-success"
                          : previewRun.status === "failed"
                            ? "bg-danger"
                            : "bg-accent animate-pulse"
                      }`}
                    />
                    <span className="text-xs font-medium text-foreground">
                      {previewRun.status === "running"
                        ? "Rendering..."
                        : previewRun.status === "completed"
                          ? "Render complete"
                          : previewRun.status === "failed"
                            ? "Render failed"
                            : "Queued"}
                    </span>
                  </div>
                  <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
                    {previewRun.logs.length === 0
                      ? "Waiting for output..."
                      : previewRun.logs.join("\n")}
                  </pre>
                </div>
              )}

              {previewVideoUrl && (
                <video
                  key={previewVideoUrl}
                  src={previewVideoUrl}
                  controls
                  loop
                  className="w-full rounded-lg border border-border bg-background"
                  style={{ aspectRatio: "16 / 9" }}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
