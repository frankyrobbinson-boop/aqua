"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ScriptCreationForm } from "@/components/ScriptCreationForm";

/**
 * Canonical creation surface. ScriptCreationForm runs without a `projectSlug`
 * prop, so POST /scripts derives the slug from the topic. We stay on this
 * page through the streaming run (the form owns its own log box) and only
 * navigate to /projects/[slug] once the script completes — ProjectView
 * doesn't currently hydrate an in-flight script task, so leaving early would
 * blank out the log.
 */
export default function NewProjectPage() {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Link
        href="/projects"
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← All projects
      </Link>

      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          New project
        </h1>
        <p className="mt-1 text-sm text-muted">
          Configure the script, then generate it on its own or run the full
          pipeline.
        </p>
      </div>

      <section className="rounded-xl border border-border bg-surface p-6">
        <ScriptCreationForm
          onRunComplete={(slug, status) => {
            if (status === "completed") {
              router.replace(`/projects/${slug}`);
            }
          }}
        />
      </section>
    </div>
  );
}
