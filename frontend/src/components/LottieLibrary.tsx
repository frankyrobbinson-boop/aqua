"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { FPS, HEIGHT, WIDTH } from "@/remotion/constants";
import { LottiePreview } from "@/remotion/LottiePreview";

// Same pattern as RemotionPanel: the Player touches browser-only APIs, so it
// must never render on the server. next/dynamic ssr:false keeps it out of SSR;
// the cast restores the generic Player type erased by dynamic's loader.
const Player = dynamic(
  () => import("@remotion/player").then((m) => m.Player),
  { ssr: false },
) as unknown as typeof import("@remotion/player").Player;

type LottieItem = { name: string; url: string };

/** Fixed loop length — mirrors the LottiePreview composition in Root.tsx. */
const PREVIEW_FRAMES = 120;

/** Strips the .json extension for a slightly friendlier label. */
function displayName(name: string): string {
  return name.replace(/\.json$/i, "");
}

export function LottieLibrary() {
  // null = still loading the initial list; [] = loaded but empty.
  const [items, setItems] = useState<LottieItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [animationData, setAnimationData] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  // Per-name cache of parsed Lottie JSON so re-selecting is instant.
  const cacheRef = useRef<Map<string, Record<string, unknown>>>(new Map());

  const loadList = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch("/api/lottie");
      if (!res.ok) throw new Error(`Could not list Lotties (${res.status})`);
      const data = (await res.json()) as LottieItem[];
      setItems(data);
      // Keep the current selection if it still exists, else fall back to first.
      setSelected((prev) =>
        prev && data.some((d) => d.name === prev)
          ? prev
          : (data[0]?.name ?? null),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Fetch (and cache) the selected animation's JSON for the Player.
  useEffect(() => {
    if (!selected) {
      setAnimationData(null);
      return;
    }
    const cached = cacheRef.current.get(selected);
    if (cached) {
      setAnimationData(cached);
      return;
    }
    let cancelled = false;
    setAnimationData(null);
    fetch(`/lottie/${encodeURIComponent(selected)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Could not load ${selected} (${r.status})`);
        return r.json() as Promise<Record<string, unknown>>;
      })
      .then((json) => {
        cacheRef.current.set(selected, json);
        if (!cancelled) setAnimationData(json);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const onRemove = useCallback(
    async (name: string) => {
      if (removing) return;
      setRemoving(name);
      setError(null);
      try {
        const res = await fetch(`/api/lottie/${encodeURIComponent(name)}`, {
          method: "DELETE",
        });
        if (!res.ok) throw new Error(`Could not remove ${name} (${res.status})`);
        cacheRef.current.delete(name);
        // Drop the selection if we just removed it; loadList reselects a valid
        // item from the refreshed list.
        if (selected === name) setSelected(null);
        await loadList();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setRemoving(null);
      }
    },
    [loadList, removing, selected],
  );

  const helper = (
    <p className="text-xs text-muted">
      Add more by dropping .json files into{" "}
      <code className="rounded bg-surface-2 px-1 py-0.5 text-muted-strong">
        frontend/public/lottie/
      </code>{" "}
      and refreshing.
    </p>
  );

  if (items === null) {
    return (
      <section className="space-y-4">
        <p className="text-sm text-muted">Loading Lottie library…</p>
      </section>
    );
  }

  if (items.length === 0) {
    return (
      <section className="space-y-4">
        <div className="rounded-xl border border-border bg-surface p-6 text-sm text-muted">
          No Lottie animations found.
        </div>
        {helper}
        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
            {error}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        {/* Selectable list */}
        <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
          <ul className="space-y-1">
            {items.map((item) => {
              const active = item.name === selected;
              return (
                <li key={item.name}>
                  <div
                    className={`flex items-center gap-2 rounded-md border px-2 py-1.5 transition-colors ${
                      active
                        ? "border-accent bg-accent/10"
                        : "border-transparent hover:bg-surface-2"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setSelected(item.name)}
                      aria-pressed={active}
                      title={item.name}
                      className={`min-w-0 flex-1 truncate text-left text-sm ${
                        active ? "text-foreground" : "text-muted"
                      }`}
                    >
                      {displayName(item.name)}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemove(item.name)}
                      disabled={removing !== null}
                      title={`Remove ${item.name}`}
                      aria-label={`Remove ${item.name}`}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-muted transition-colors hover:border-danger/40 hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Preview */}
        <div className="space-y-4">
          <div className="overflow-hidden rounded-lg border border-border bg-background">
            <Player
              key={selected ?? "none"}
              component={LottiePreview}
              inputProps={{ animationData }}
              durationInFrames={PREVIEW_FRAMES}
              fps={FPS}
              compositionWidth={WIDTH}
              compositionHeight={HEIGHT}
              style={{ width: "100%", aspectRatio: "16 / 9" }}
              controls
              autoPlay
              loop
            />
          </div>
          {selected && (
            <p className="text-sm font-medium text-foreground">
              {displayName(selected)}
            </p>
          )}
          {helper}
          {error && (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
              {error}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function TrashIcon() {
  // 14px inline SVG (matches the app's inline-icon convention). currentColor so
  // the button's hover color carries through.
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className="h-3.5 w-3.5"
    >
      <path d="M3 4.5h10" strokeLinecap="round" />
      <path d="M6.5 4.5V3.5A1 1 0 0 1 7.5 2.5h1A1 1 0 0 1 9.5 3.5v1" />
      <path d="M4.5 4.5l.5 8a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1l.5-8" />
      <path d="M6.75 7v4M9.25 7v4" strokeLinecap="round" />
    </svg>
  );
}
