"use client";

/**
 * 8-swatch picker mirroring backend/services/channel_migration.py's
 * deterministic palette. A 9th option lets the user paste any `#rrggbb`
 * value if none of the swatches fit.
 *
 * Pure presentational — no fetching, no state beyond what the parent owns.
 */

const PALETTE: ReadonlyArray<{ hex: string; label: string }> = [
  { hex: "#4a7c3a", label: "Gardening green" },
  { hex: "#3a5a7c", label: "Cool blue" },
  { hex: "#7c3a5a", label: "Plum" },
  { hex: "#7c5a3a", label: "Warm earth" },
  { hex: "#3a7c7c", label: "Teal" },
  { hex: "#5a3a7c", label: "Violet" },
  { hex: "#7c7c3a", label: "Olive" },
  { hex: "#3a7c5a", label: "Forest" },
];

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

type Props = {
  value: string;
  onChange: (hex: string) => void;
  disabled?: boolean;
};

export function ColorSwatchPicker({ value, onChange, disabled }: Props) {
  const normalized = value?.toLowerCase() ?? "";
  const matchesPalette = PALETTE.some((p) => p.hex.toLowerCase() === normalized);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {PALETTE.map((p) => {
          const selected = p.hex.toLowerCase() === normalized;
          return (
            <button
              key={p.hex}
              type="button"
              title={p.label}
              aria-label={p.label}
              aria-pressed={selected}
              onClick={() => onChange(p.hex)}
              disabled={disabled}
              className={`h-7 w-7 rounded-full border transition-transform ${
                selected
                  ? "border-foreground ring-2 ring-accent ring-offset-2 ring-offset-background scale-110"
                  : "border-border hover:scale-110"
              } disabled:cursor-not-allowed disabled:opacity-50`}
              style={{ backgroundColor: p.hex }}
            />
          );
        })}
      </div>
      <div className="flex items-center gap-2">
        <span
          className="h-5 w-5 rounded border border-border"
          style={{ backgroundColor: HEX_RE.test(value) ? value : "transparent" }}
        />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#rrggbb"
          disabled={disabled}
          spellCheck={false}
          className="form-input font-mono text-xs w-32"
        />
        {!matchesPalette && HEX_RE.test(value) && (
          <span className="text-xs text-muted">Custom</span>
        )}
        {value && !HEX_RE.test(value) && (
          <span className="text-xs text-danger">Invalid hex</span>
        )}
      </div>
    </div>
  );
}
