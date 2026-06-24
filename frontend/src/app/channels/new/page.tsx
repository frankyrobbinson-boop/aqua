import Link from "next/link";
import { ChannelCreateWizard } from "@/components/ChannelCreateWizard";

/**
 * Phase 3c — the "Create a New Channel" wizard. Pure client wrapper around
 * ChannelCreateWizard; no server data needed up front (the wizard fetches
 * the prompt-model list on demand for its visuals step).
 */
export default function NewChannelPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Link
        href="/channels"
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← All channels
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Create a New Channel
        </h1>
        <p className="mt-1 text-sm text-muted">
          Identity, voice, and visual style — fill in the basics and you can
          refine the rest in the channel editor.
        </p>
      </div>

      <ChannelCreateWizard />
    </div>
  );
}
