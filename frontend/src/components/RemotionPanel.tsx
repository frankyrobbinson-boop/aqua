"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ColorField } from "@/components/ColorField";
import {
  remotionOutUrl,
  startRemotionRender,
  streamTaskLogs,
  type TaskStatus,
} from "@/lib/api";
import { FPS, HEIGHT, WIDTH } from "@/remotion/constants";
import {
  ANIMATION_OPTIONS,
  BACKGROUND_OPTIONS,
  CARD_DEFAULTS,
  DECORATION_SETS,
  DENSITY_OPTIONS,
  FONT_OPTIONS,
} from "@/remotion/cards/defaults";
import { CARDS } from "@/remotion/cards/registry";
import type {
  CardAnimation,
  CardBackground,
  CardProps,
  DecorationDensity,
  DecorationSet,
} from "@/remotion/cards/types";

// The Player touches browser-only APIs, so it must never render on the server.
// next/dynamic with ssr:false keeps it out of the SSR pass. The cast restores
// the generic Player type (erased by dynamic's loader). `typeof import(...)` is
// a type-only query — erased at compile time, no runtime import.
const Player = dynamic(
  () => import("@remotion/player").then((m) => m.Player),
  { ssr: false },
) as unknown as typeof import("@remotion/player").Player;

type RunState = {
  taskId: string;
  logs: string[];
  status: TaskStatus;
  filename: string;
};

const FIELD_CLASS =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent";

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
  disabled,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ id: string; label: string }>;
  disabled?: boolean;
}) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={`${FIELD_CLASS} cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function RemotionPanel() {
  const [cardId, setCardId] = useState<string>(CARDS[0].id);
  const [props, setProps] = useState<CardProps>(CARD_DEFAULTS);
  const [run, setRun] = useState<RunState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Close any open SSE stream on unmount.
  useEffect(() => () => cleanupRef.current?.(), []);

  const selected = CARDS.find((c) => c.id === cardId) ?? CARDS[0];
  const running = submitting || run?.status === "running";
  const durationInFrames = Math.round(props.durationInSeconds * FPS);

  function update<K extends keyof CardProps>(key: K, value: CardProps[K]) {
    setProps((prev) => ({ ...prev, [key]: value }));
  }
  function updatePalette(key: keyof CardProps["palette"], hex: string) {
    setProps((prev) => ({ ...prev, palette: { ...prev.palette, [key]: hex } }));
  }
  function updateDecoration(
    key: keyof CardProps["decoration"],
    value: string,
  ) {
    setProps((prev) => ({
      ...prev,
      decoration: { ...prev.decoration, [key]: value },
    }));
  }

  async function onRender() {
    if (running) return;
    setError(null);
    setSubmitting(true);
    cleanupRef.current?.();
    try {
      const { task_id, filename } = await startRemotionRender(cardId, props);
      setRun({ taskId: task_id, logs: [], status: "running", filename });
      cleanupRef.current = streamTaskLogs(
        task_id,
        (line) =>
          setRun((prev) =>
            prev ? { ...prev, logs: [...prev.logs, line] } : prev,
          ),
        (status) => setRun((prev) => (prev ? { ...prev, status } : prev)),
        (err) => setError(err instanceof Error ? err.message : String(err)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const videoUrl =
    run?.status === "completed" ? remotionOutUrl(run.filename) : null;
  const titleEmpty = props.title.trim().length === 0;

  return (
    <section className="space-y-6">
      {/* Card picker */}
      <div className="flex flex-wrap gap-2">
        {CARDS.map((card) => {
          const active = card.id === cardId;
          return (
            <button
              key={card.id}
              type="button"
              onClick={() => setCardId(card.id)}
              title={card.description}
              aria-pressed={active}
              className={`rounded-md border px-3.5 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border bg-surface text-muted hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              {card.label}
            </button>
          );
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        {/* Controls */}
        <div className="space-y-5 rounded-xl border border-border bg-surface p-5">
          <Field label="Title" htmlFor="card-title">
            <input
              id="card-title"
              type="text"
              value={props.title}
              onChange={(e) => update("title", e.target.value)}
              maxLength={120}
              placeholder="Enter a title..."
              className={FIELD_CLASS}
            />
          </Field>

          <Field label="Subtitle" htmlFor="card-subtitle">
            <input
              id="card-subtitle"
              type="text"
              value={props.subtitle ?? ""}
              onChange={(e) => update("subtitle", e.target.value)}
              maxLength={200}
              placeholder="Optional subtitle..."
              className={FIELD_CLASS}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Animation" htmlFor="card-animation">
              <Select
                id="card-animation"
                value={props.animation}
                onChange={(v) => update("animation", v as CardAnimation)}
                options={ANIMATION_OPTIONS}
              />
            </Field>
            <Field label="Font" htmlFor="card-font">
              <Select
                id="card-font"
                value={props.fontFamily}
                onChange={(v) => update("fontFamily", v)}
                options={FONT_OPTIONS}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Background" htmlFor="card-background">
              <Select
                id="card-background"
                value={props.background}
                onChange={(v) => update("background", v as CardBackground)}
                options={BACKGROUND_OPTIONS}
              />
            </Field>
            <div />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Decoration" htmlFor="card-decoration-set">
              <Select
                id="card-decoration-set"
                value={props.decoration.set}
                onChange={(v) =>
                  updateDecoration("set", v as DecorationSet)
                }
                options={DECORATION_SETS}
              />
            </Field>
            <Field label="Density" htmlFor="card-decoration-density">
              <Select
                id="card-decoration-density"
                value={props.decoration.density}
                onChange={(v) =>
                  updateDecoration("density", v as DecorationDensity)
                }
                options={DENSITY_OPTIONS}
              />
            </Field>
          </div>

          <Field label="Background color">
            <ColorField
              value={props.palette.background}
              onChange={(hex) => updatePalette("background", hex)}
            />
          </Field>
          <Field label="Text color">
            <ColorField
              value={props.palette.text}
              onChange={(hex) => updatePalette("text", hex)}
            />
          </Field>
          <Field label="Accent color">
            <ColorField
              value={props.palette.accent}
              onChange={(hex) => updatePalette("accent", hex)}
            />
          </Field>

          <Field label="Duration" htmlFor="card-duration">
            <div className="flex items-center gap-3">
              <input
                id="card-duration"
                type="range"
                min={2}
                max={20}
                step={1}
                value={props.durationInSeconds}
                onChange={(e) =>
                  update("durationInSeconds", Number(e.target.value))
                }
                className="flex-1 accent-accent"
              />
              <span className="w-10 text-right text-sm font-medium tabular-nums text-foreground">
                {props.durationInSeconds}s
              </span>
            </div>
          </Field>
        </div>

        {/* Preview + render + output */}
        <div className="space-y-4">
          <div className="overflow-hidden rounded-lg border border-border bg-background">
            <Player
              key={cardId}
              component={selected.component}
              inputProps={props}
              durationInFrames={durationInFrames}
              fps={FPS}
              compositionWidth={WIDTH}
              compositionHeight={HEIGHT}
              style={{ width: "100%", aspectRatio: "16 / 9" }}
              controls
              autoPlay
              loop
            />
          </div>

          <button
            type="button"
            onClick={onRender}
            disabled={running || titleEmpty}
            className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
          >
            {submitting
              ? "Starting..."
              : run?.status === "running"
                ? "Rendering..."
                : "Render to MP4"}
          </button>

          {error && (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
              {error}
            </div>
          )}

          {run && (
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
                    ? "Rendering..."
                    : run.status === "completed"
                      ? "Render complete"
                      : run.status === "failed"
                        ? "Render failed"
                        : "Queued"}
                </span>
              </div>
              <pre className="max-h-72 overflow-auto px-4 py-2 font-mono text-xs leading-relaxed text-muted-strong">
                {run.logs.length === 0
                  ? "Waiting for output..."
                  : run.logs.join("\n")}
              </pre>
            </div>
          )}

          {videoUrl && (
            <div className="rounded-xl border border-border bg-surface p-5">
              <h2 className="mb-3 text-sm font-medium text-foreground">
                Result
              </h2>
              <video
                key={videoUrl}
                src={videoUrl}
                controls
                className="w-full rounded-lg border border-border bg-background"
                style={{ aspectRatio: "16 / 9" }}
              />
              <a
                href={videoUrl}
                download
                className="mt-4 inline-block rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
              >
                Download MP4
              </a>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
