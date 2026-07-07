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
  CARD_DEFAULT_OVERRIDES,
  DECORATION_SETS,
  DENSITY_OPTIONS,
  FONT_OPTIONS,
  LOTTIE_DENSITY_OPTIONS,
} from "@/remotion/cards/defaults";
import { CARDS } from "@/remotion/cards/registry";
import type {
  CardAnimation,
  CardBackground,
  CardProps,
  DecorationDensity,
  DecorationSet,
  LottieAnimationEntry,
  LottieDensity,
  LottieRuntimeEntry,
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

/** One entry from `GET /api/lottie` (mirrors LottieLibrary). */
type LottieItem = { name: string; url: string };

/** Cap on the GardenBloom animation rows — keeps the list sane. */
const LOTTIE_MAX_ROWS = 4;

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

/** Base defaults with the card's per-card overrides applied, so switching cards
 *  seeds the form with that card's signature palette/props (see defaults.ts). */
function mergedDefaults(id: string): CardProps {
  return { ...CARD_DEFAULTS, ...(CARD_DEFAULT_OVERRIDES[id] ?? {}) };
}

export function RemotionPanel() {
  const [cardId, setCardId] = useState<string>(CARDS[0].id);
  const [props, setProps] = useState<CardProps>(() =>
    mergedDefaults(CARDS[0].id),
  );
  const [run, setRun] = useState<RunState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Lottie decorations (GardenBloom): the library list for the row dropdowns,
  // plus the fetched JSON for each chosen animation — assembled (aligned to
  // props.lottieAnimations, each paired with its loop flag) and injected into
  // the Player's inputProps.
  const [lottieList, setLottieList] = useState<LottieItem[] | null>(null);
  const [lottieData, setLottieData] = useState<Array<LottieRuntimeEntry | null>>(
    [],
  );
  const lottieCacheRef = useRef<Map<string, Record<string, unknown>>>(new Map());

  // Close any open SSE stream on unmount.
  useEffect(() => () => cleanupRef.current?.(), []);

  // Load the Lottie library once so the animation-row dropdowns list every
  // animation (and pick up newly added ones on reload).
  useEffect(() => {
    let cancelled = false;
    fetch("/api/lottie")
      .then((r) =>
        r.ok
          ? (r.json() as Promise<LottieItem[]>)
          : Promise.reject(new Error(String(r.status))),
      )
      .then((data) => {
        if (!cancelled) setLottieList(data);
      })
      .catch(() => {
        // Non-fatal: the dropdown just shows "None". Don't hijack the render
        // error box, which is scoped to MP4 renders.
        if (!cancelled) setLottieList([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = CARDS.find((c) => c.id === cardId) ?? CARDS[0];
  const running = submitting || run?.status === "running";
  const durationInFrames = Math.round(props.durationInSeconds * FPS);
  const lottieAnimations = props.lottieAnimations ?? [];

  // Fetch (and cache, by name) each chosen animation's JSON, then assemble the
  // runtime `lottieData` array aligned to props.lottieAnimations — each paired
  // with its loop flag, null until its JSON loads (or if it failed / is "None").
  // Fed to the Player so GardenBloom layers the animations live. Toggling loop
  // or reordering rows reassembles from the cache without refetching.
  useEffect(() => {
    const entries = props.lottieAnimations ?? [];
    let cancelled = false;

    const assemble = (): Array<LottieRuntimeEntry | null> =>
      entries.map((e) => {
        const data = e.name ? lottieCacheRef.current.get(e.name) : undefined;
        return data ? { data, loop: e.loop } : null;
      });

    // Reflect whatever's already cached immediately (snappy loop toggles).
    setLottieData(assemble());

    const uncached = Array.from(
      new Set(entries.map((e) => e.name).filter(Boolean)),
    ).filter((name) => !lottieCacheRef.current.has(name));
    if (uncached.length === 0) return;

    Promise.all(
      uncached.map((name) =>
        fetch(`/lottie/${encodeURIComponent(name)}`)
          .then((r) =>
            r.ok
              ? (r.json() as Promise<Record<string, unknown>>)
              : Promise.reject(new Error(String(r.status))),
          )
          .then((json) => {
            lottieCacheRef.current.set(name, json);
          })
          .catch(() => {
            // Non-fatal: that row stays null (its slot shows nothing; the SVG
            // botanicals still render). Don't hijack the MP4 render error box.
          }),
      ),
    ).then(() => {
      if (!cancelled) setLottieData(assemble());
    });

    return () => {
      cancelled = true;
    };
  }, [props.lottieAnimations]);

  // Switching cards reseeds the form with that card's merged defaults, so e.g.
  // Premium boots with its muted palette + kicker.
  function selectCard(id: string) {
    setCardId(id);
    setProps(mergedDefaults(id));
  }

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

  // Lottie animation rows (GardenBloom) — add/remove/edit the list of chosen
  // animations. New rows default to the first library animation (looping).
  function updateLottieRow(index: number, patch: Partial<LottieAnimationEntry>) {
    setProps((prev) => {
      const list = [...(prev.lottieAnimations ?? [])];
      list[index] = { ...list[index], ...patch };
      return { ...prev, lottieAnimations: list };
    });
  }
  function addLottieRow() {
    setProps((prev) => {
      const list = [...(prev.lottieAnimations ?? [])];
      if (list.length >= LOTTIE_MAX_ROWS) return prev;
      list.push({ name: lottieList?.[0]?.name ?? "", loop: true });
      return { ...prev, lottieAnimations: list };
    });
  }
  function removeLottieRow(index: number) {
    setProps((prev) => ({
      ...prev,
      lottieAnimations: (prev.lottieAnimations ?? []).filter(
        (_, i) => i !== index,
      ),
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

  // The Lottie decoration is a GardenBloom-only evaluation aid, so its controls
  // only show for that card (other cards keep the SVG botanicals).
  const isBloom = cardId === "GardenBloom";
  const lottieOptions = [
    { id: "", label: "None" },
    ...(lottieList ?? []).map((it) => ({ id: it.name, label: it.name })),
  ];

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
              onClick={() => selectCard(card.id)}
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
            <Field label="Eyebrow" htmlFor="card-eyebrow">
              <input
                id="card-eyebrow"
                type="text"
                value={props.eyebrow ?? ""}
                onChange={(e) => update("eyebrow", e.target.value)}
                maxLength={40}
                placeholder="Optional kicker..."
                className={FIELD_CLASS}
              />
            </Field>
            <Field label="Highlight word" htmlFor="card-highlight">
              <input
                id="card-highlight"
                type="text"
                value={props.highlight ?? ""}
                onChange={(e) => update("highlight", e.target.value)}
                maxLength={60}
                placeholder="Word to accent..."
                className={FIELD_CLASS}
              />
            </Field>
          </div>

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

          {isBloom && (
            <>
              <Field label="Decoration animations">
                <div className="space-y-2">
                  {lottieAnimations.length === 0 ? (
                    <p className="text-xs text-muted">
                      None — showing the SVG botanicals only.
                    </p>
                  ) : (
                    lottieAnimations.map((entry, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <div className="flex-1">
                          <Select
                            value={entry.name}
                            onChange={(v) => updateLottieRow(i, { name: v })}
                            options={lottieOptions}
                          />
                        </div>
                        <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-strong">
                          <input
                            type="checkbox"
                            checked={entry.loop}
                            onChange={(e) =>
                              updateLottieRow(i, { loop: e.target.checked })
                            }
                            className="h-4 w-4 cursor-pointer accent-accent"
                          />
                          loop
                        </label>
                        <button
                          type="button"
                          onClick={() => removeLottieRow(i)}
                          aria-label="Remove animation"
                          className="shrink-0 rounded-md border border-border bg-surface px-2.5 py-2 text-sm leading-none text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
                        >
                          ✕
                        </button>
                      </div>
                    ))
                  )}
                  {lottieAnimations.length < LOTTIE_MAX_ROWS && (
                    <button
                      type="button"
                      onClick={addLottieRow}
                      className="w-full rounded-md border border-dashed border-border bg-surface px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
                    >
                      + Add animation
                    </button>
                  )}
                </div>
              </Field>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Animation density" htmlFor="card-lottie-density">
                  <Select
                    id="card-lottie-density"
                    value={props.lottieDensity ?? "low"}
                    onChange={(v) => update("lottieDensity", v as LottieDensity)}
                    options={LOTTIE_DENSITY_OPTIONS}
                  />
                </Field>
                <div />
              </div>

              {lottieAnimations.length > 0 && (
                <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-muted-strong">
                  <input
                    type="checkbox"
                    checked={props.lottieRecolor ?? true}
                    onChange={(e) => update("lottieRecolor", e.target.checked)}
                    className="h-4 w-4 cursor-pointer accent-accent"
                  />
                  Recolor Lottie to palette
                </label>
              )}
            </>
          )}

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
              inputProps={{ ...props, lottieData }}
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
