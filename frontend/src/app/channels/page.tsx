import Link from "next/link";
import { getChannels } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  let data;
  let error: string | null = null;
  try {
    data = await getChannels();
  } catch (err) {
    data = { default_channel: "", channels: [] };
    error = err instanceof Error ? err.message : String(err);
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Channels</h1>
          <p className="mt-1 text-sm text-muted">
            Channel presets define narrator voice, audience, tone, and visual style.
            Click a channel to edit it.
          </p>
        </div>
        <Link
          href="/channels/new"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover"
        >
          + New channel
        </Link>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
          Could not reach API at <span className="font-mono">{error}</span>.
          Is the FastAPI service running on port 8000?
        </div>
      )}

      {data.channels.length === 0 && !error ? (
        <div className="rounded-xl border border-dashed border-border bg-surface/40 p-12 text-center">
          <p className="text-sm text-muted">No channels configured.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.channels.map((c) => (
            <Link
              key={c.id}
              href={`/channels/${c.id}`}
              className="block rounded-lg border border-border bg-surface p-5 hover:border-accent hover:bg-surface-2 transition-colors"
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className="h-3 w-3 rounded-full border border-border"
                    style={{ backgroundColor: c.color }}
                    aria-hidden
                  />
                  <h2 className="font-medium text-foreground">{c.name}</h2>
                </div>
                {c.id === data.default_channel && (
                  <span className="text-[10px] uppercase tracking-wide text-muted">Default</span>
                )}
              </div>
              <p className="mt-1 font-mono text-xs text-muted">{c.id}</p>
              <p className="mt-3 text-sm text-muted-strong">{c.description}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
