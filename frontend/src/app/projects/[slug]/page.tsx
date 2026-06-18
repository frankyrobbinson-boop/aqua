import Link from "next/link";
import { notFound } from "next/navigation";
import { getProject, getScenes, type SceneInfo } from "@/lib/api";
import { ProjectView } from "@/components/ProjectView";
import { StatusBadge } from "@/components/StatusBadge";
import { DeleteProjectButton } from "@/components/DeleteProjectButton";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ slug: string }>;
};

export default async function ProjectPage({ params }: Props) {
  const { slug } = await params;

  let project;
  let scenes: SceneInfo[] = [];
  try {
    project = await getProject(slug);
    scenes = await getScenes(slug);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <Link
        href="/projects"
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← All projects
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {project.has_script ? project.title : "Untitled draft"}
          </h1>
          <p className="mt-1 font-mono text-xs text-muted">{slug}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap gap-1.5">
            <StatusBadge label="Script" active={project.has_script} />
            <StatusBadge label="Audio" active={project.has_audio} />
            <StatusBadge label="Video" active={project.has_video} />
          </div>
          <DeleteProjectButton
            slug={slug}
            title={project.has_script ? project.title : slug}
          />
        </div>
      </div>

      <ProjectView slug={slug} project={project} scenes={scenes} />
    </div>
  );
}
