"use client";

import { useEffect, useState } from "react";
import { getVideoTypes, type VideoType } from "@/lib/api";

type Props = {
  value: string | undefined;
  onChange: (typeId: string) => void;
  disabled?: boolean;
};

export function VideoTypeSelect({ value, onChange, disabled }: Props) {
  const [types, setTypes] = useState<VideoType[]>([]);
  const [defaultType, setDefaultType] = useState<string>("default");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getVideoTypes()
      .then((res) => {
        if (!mounted) return;
        setTypes(res.types);
        setDefaultType(res.default_type);
        if (!value) onChange(res.default_type);
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      mounted = false;
    };
    // intentionally only on mount — re-fetching on every parent rerender would thrash
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = types.find((t) => t.id === (value || defaultType));

  return (
    <div>
      <select
        value={value ?? defaultType}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || types.length === 0}
        className="form-input"
      >
        {types.length === 0 && <option>Loading...</option>}
        {types.map((t) => (
          <option key={t.id} value={t.id}>
            {t.label}
          </option>
        ))}
      </select>
      {current && (
        <p className="mt-1 text-xs text-muted">{current.description}</p>
      )}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
