"use client";

import { useEffect, useState } from "react";
import { getChannels, type Channel } from "@/lib/api";

type Props = {
  value: string | undefined;
  onChange: (id: string) => void;
  disabled?: boolean;
};

export function ChannelSelect({ value, onChange, disabled }: Props) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [defaultChannel, setDefaultChannel] = useState<string>("default");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getChannels()
      .then((res) => {
        if (!mounted) return;
        setChannels(res.channels);
        setDefaultChannel(res.default_channel);
        if (!value) onChange(res.default_channel);
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

  const current = channels.find((c) => c.id === (value || defaultChannel));

  return (
    <div>
      <select
        value={value ?? defaultChannel}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || channels.length === 0}
        className="form-input"
      >
        {channels.length === 0 && <option>Loading...</option>}
        {channels.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
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
