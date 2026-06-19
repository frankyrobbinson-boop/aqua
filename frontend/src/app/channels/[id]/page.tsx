import Link from "next/link";
import { notFound } from "next/navigation";
import { getChannel } from "@/lib/api";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export default async function ChannelDetailPage({ params }: Props) {
  const { id } = await params;

  let channel;
  try {
    channel = await getChannel(id);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <Link
        href="/channels"
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← All channels
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{channel.name}</h1>
        <p className="mt-1 font-mono text-xs text-muted">{channel.id}</p>
        <p className="mt-3 text-sm text-muted-strong">{channel.description}</p>
        {channel.preferred_hook_archetype_label && (
          <div className="mt-4 inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-xs">
            <span className="text-muted">Preferred opening:</span>
            <span className="font-medium text-foreground">{channel.preferred_hook_archetype_label}</span>
          </div>
        )}
      </div>

      {Object.keys(channel.sections).length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-surface/40 p-8 text-center text-sm text-muted">
          This channel module has no <span className="font-mono">## </span> sections.
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(channel.sections).map(([heading, body]) => (
            <section key={heading} className="rounded-lg border border-border bg-surface p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-strong">{heading}</h2>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground">{body}</pre>
            </section>
          ))}
        </div>
      )}

      <p className="mt-8 text-xs text-muted">
        Read-only for now. Edit <span className="font-mono">backend/prompts/channels/{channel.id}.md</span> to change this channel.
      </p>
    </div>
  );
}
