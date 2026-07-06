"use client";

/**
 * Full color control for the Remotion card designer: a native OS color picker
 * (the clickable swatch) synced to a hex text field. Picking a color updates
 * the hex field; typing a valid hex updates the swatch. Both drive the same
 * `onChange`.
 *
 * Pure presentational — no state beyond what's needed; the parent owns `value`.
 */

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

type Props = {
  value: string;
  onChange: (hex: string) => void;
  disabled?: boolean;
};

export function ColorField({ value, onChange, disabled }: Props) {
  // <input type="color"> requires a valid `#rrggbb`. When the current value
  // isn't one (e.g. mid-edit), fall back to a safe default for display only —
  // never overwrite state.
  const swatchValue = HEX_RE.test(value) ? value : "#000000";

  return (
    <div className="flex items-center gap-2">
      <input
        type="color"
        value={swatchValue}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label="Color picker"
        className="h-9 w-9 rounded-md border border-border p-0 cursor-pointer bg-transparent disabled:cursor-not-allowed disabled:opacity-50"
      />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="#rrggbb"
        disabled={disabled}
        spellCheck={false}
        className="w-28 rounded-md border border-border bg-background px-3 py-2 text-sm font-mono text-foreground outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
      />
      {value && !HEX_RE.test(value) && (
        <span className="text-xs text-danger">Invalid hex</span>
      )}
    </div>
  );
}
