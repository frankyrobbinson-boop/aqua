import Link from "next/link";
import { StatusBadge } from "./StatusBadge";
import type { ProjectSummary } from "@/lib/api";

function formatRelative(epochSeconds: number): string {
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleDateString();
}

export function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <Link
      href={`/projects/${project.slug}`}
      className="group block rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong hover:bg-surface-2"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="line-clamp-2 text-base font-semibold leading-snug text-foreground group-hover:text-accent">
          {project.title}
        </h3>
      </div>
      <p className="mt-1 truncate font-mono text-xs text-muted">
        {project.slug}
      </p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        <StatusBadge label="Script" active={project.has_script} />
        <StatusBadge label="Audio" active={project.has_audio} />
        <StatusBadge label="Video" active={project.has_video} />
      </div>
      <p className="mt-3 text-xs text-muted">
        Updated {formatRelative(project.modified_at)}
      </p>
    </Link>
  );
}
