import Link from "next/link";
import { notFound } from "next/navigation";
import { getChannelPreset } from "@/lib/api";
import { ChannelEditPanel } from "@/components/ChannelEditPanel";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

/**
 * Phase 3b: the channel detail page is now a read-write editor. The server
 * component only fetches the preset to render the page title + 404 guard;
 * all editing happens inside the ChannelEditPanel client component, which
 * owns its own queries, debounced autosave, and status indicator.
 */
export default async function ChannelDetailPage({ params }: Props) {
  const { id } = await params;

  let preset;
  try {
    preset = await getChannelPreset(id);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Link
        href="/channels"
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← All channels
      </Link>

      <div className="mb-6 flex items-center gap-3">
        <span
          className="h-4 w-4 rounded-full border border-border"
          style={{ backgroundColor: preset.color }}
          aria-hidden
        />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {preset.label}
        </h1>
      </div>

      <ChannelEditPanel id={id} />
    </div>
  );
}
