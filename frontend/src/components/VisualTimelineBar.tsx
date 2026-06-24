"use client";

/**
 * Horizontal segment timeline. Each segment is a colored slice sized by its
 * duration; boundary timecodes appear below the bar at each segment edge.
 *
 * The colors cycle through a short palette derived from CSS vars so the bar
 * reads as "different segments" without inventing a new color per segment.
 */
export type TimelineSegment = {
  /** Stable key for React. Usually the segment_id from visual_config. */
  key: string;
  label: string;
  /** Start time in seconds. */
  start: number;
  /** End time in seconds. */
  end: number;
};

const COLORS = [
  "var(--accent)",
  "var(--accent-2)",
  "var(--success)",
  "var(--warning)",
  "var(--muted-strong)",
];

export function VisualTimelineBar({
  segments,
}: {
  segments: TimelineSegment[];
}) {
  if (segments.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-surface/40 p-4 text-center text-xs text-muted">
        No segment timing yet — generate the voiceover first to see the
        timeline.
      </div>
    );
  }

  const total = segments[segments.length - 1].end - segments[0].start;
  const safeTotal = total > 0 ? total : 1;
  const origin = segments[0].start;

  return (
    <div>
      <div className="flex h-8 w-full overflow-hidden rounded-md border border-border bg-surface-2">
        {segments.map((seg, i) => {
          const width = ((seg.end - seg.start) / safeTotal) * 100;
          return (
            <div
              key={seg.key}
              title={`${seg.label} (${fmt(seg.start)} — ${fmt(seg.end)})`}
              className="flex items-center justify-center text-[10px] font-medium text-white/90"
              style={{
                width: `${width}%`,
                background: COLORS[i % COLORS.length],
                opacity: 0.55,
              }}
            >
              {width > 6 ? seg.label : ""}
            </div>
          );
        })}
      </div>
      <div className="relative mt-1 h-4 w-full">
        {segments.map((seg, i) => {
          const left = ((seg.start - origin) / safeTotal) * 100;
          return (
            <span
              key={`${seg.key}-start`}
              className="absolute top-0 -translate-x-1/2 font-mono text-[10px] text-muted"
              style={{ left: `${left}%` }}
            >
              {fmt(seg.start)}
            </span>
          );
        })}
        <span
          className="absolute top-0 -translate-x-full font-mono text-[10px] text-muted"
          style={{ left: "100%" }}
        >
          {fmt(segments[segments.length - 1].end)}
        </span>
      </div>
    </div>
  );
}

/** mm:ss with one decimal. Matches the per-row time range formatting. */
function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}
