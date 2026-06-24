"use client";

import type { VisualProvider } from "@/lib/api";

/**
 * Provider <select> filtered by the segment's current mode.
 *
 * Unavailable providers are still listed (so the user sees what's coming) but
 * disabled at the option level. The label suffix marks them so they stand out
 * in the dropdown.
 */
type Props = {
  providers: VisualProvider[];
  mode: string;
  value: string;
  onChange: (providerId: string) => void;
  disabled?: boolean;
};

export function ProviderDropdown({
  providers,
  mode,
  value,
  onChange,
  disabled,
}: Props) {
  const matching = providers.filter((p) => p.mode === mode);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || matching.length === 0}
      className="rounded-md border border-border bg-surface-2 px-2 py-1.5 text-xs text-foreground outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
    >
      {matching.length === 0 && <option value="">No provider</option>}
      {matching.map((p) => (
        <option key={p.id} value={p.id} disabled={!p.available}>
          {p.label}
          {!p.available ? " (coming soon)" : ""}
        </option>
      ))}
    </select>
  );
}
