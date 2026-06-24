"use client";

import { useProjectsListQuery } from "@/lib/queries";
import { ProjectCard } from "@/components/ProjectCard";
import { NewProjectButton } from "@/components/NewProjectButton";

export default function ProjectsPage() {
  const { data, error, isLoading } = useProjectsListQuery();
  const projects = data ?? [];
  const errorMessage = error
    ? error instanceof Error
      ? error.message
      : String(error)
    : null;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Projects
          </h1>
          <p className="mt-1 text-sm text-muted">
            All videos you&apos;ve generated, in progress, or drafted.
          </p>
        </div>
        <NewProjectButton />
      </div>

      {errorMessage && (
        <div className="mb-6 rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
          Could not reach API at <span className="font-mono">{errorMessage}</span>.
          Is the FastAPI service running on port 8000?
        </div>
      )}

      {isLoading ? (
        <div className="rounded-xl border border-dashed border-border bg-surface/40 p-12 text-center text-sm text-muted">
          Loading projects...
        </div>
      ) : projects.length === 0 && !errorMessage ? (
        <div className="rounded-xl border border-dashed border-border bg-surface/40 p-12 text-center">
          <p className="text-sm text-muted">
            No projects yet. Click <span className="font-medium text-foreground">New project</span> to start.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <ProjectCard key={p.slug} project={p} />
          ))}
        </div>
      )}
    </div>
  );
}
