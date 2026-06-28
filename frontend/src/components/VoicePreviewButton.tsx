"use client";

import { useEffect, useRef, useState } from "react";
import { previewChannelVoice } from "@/lib/api";

type Props = {
  channelId: string;
  text?: string;
};

export function VoicePreviewButton({ channelId, text }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Revoke the previous blob URL when a new one supersedes it so we don't
  // leak per-preview blobs across rapid clicks.
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  async function onPlay() {
    setError(null);
    setLoading(true);
    try {
      const blob = await previewChannelVoice(channelId, text);
      const url = URL.createObjectURL(blob);
      setAudioUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      // Defer to the next tick so the <audio src> binds before .play().
      setTimeout(() => audioRef.current?.play().catch(() => {}), 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onPlay}
        disabled={loading}
        className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-3 disabled:opacity-50"
      >
        {loading ? "Generating..." : "Preview voice"}
      </button>
      {audioUrl && (
        <audio ref={audioRef} src={audioUrl} controls className="h-8" />
      )}
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
