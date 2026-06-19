"use client";

import { useEffect, useState } from "react";
import { getHookArchetypes, type HookArchetype } from "@/lib/api";

type Props = {
  value: string | undefined;
  onChange: (archetypeId: string | undefined) => void;
  disabled?: boolean;
};

export function HookArchetypeSelect({ value, onChange, disabled }: Props) {
  const [archetypes, setArchetypes] = useState<HookArchetype[]>([]);
  const [defaultArchetype, setDefaultArchetype] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getHookArchetypes()
      .then((res) => {
        if (!mounted) return;
        setArchetypes(res.archetypes);
        setDefaultArchetype(res.default_archetype);
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      mounted = false;
    };
    // intentionally only on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const defaultLabel = archetypes.find((a) => a.id === defaultArchetype);
  const current = value ? archetypes.find((a) => a.id === value) : null;

  return (
    <div>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        disabled={disabled || archetypes.length === 0}
        className="form-input"
      >
        {archetypes.length === 0 && <option>Loading...</option>}
        {archetypes.length > 0 && (
          <option value="">Channel default</option>
        )}
        {archetypes.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label}
          </option>
        ))}
      </select>
      {current ? (
        <p className="mt-1 text-xs text-muted">{current.description}</p>
      ) : defaultLabel ? (
        <p className="mt-1 text-xs text-muted">
          Channel default: {defaultLabel.label} — {defaultLabel.description}
        </p>
      ) : null}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
