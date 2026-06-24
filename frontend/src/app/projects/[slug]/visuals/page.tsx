import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getProject,
  getScenes,
  getVisualConfig,
  getVisualProviders,
  type SceneInfo,
} from "@/lib/api";
import { StepIndicator, type WizardStep } from "@/components/StepIndicator";
import { VisualPacingPanel } from "@/components/VisualPacingPanel";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ slug: string }>;
};

/**
 * Generate Visuals — dedicated full-page wizard, step 3 of 4. Loads everything
 * server-side so the panel mounts with config + scenes already in hand; the
 * client-side panel handles edits, autosave, and the generate dispatch.
 */
export default async function VisualsPage({ params }: Props) {
  const { slug } = await params;

  let project;
  let scenes: SceneInfo[] = [];
  let providers;
  let visualConfig;
  try {
    [project, scenes, providers, visualConfig] = await Promise.all([
      getProject(slug),
      getScenes(slug),
      getVisualProviders(),
      getVisualConfig(slug),
    ]);
  } catch {
    notFound();
  }

  const title = project.has_script ? project.title : slug;
  const steps: WizardStep[] = [
    { label: "Script", status: project.has_script ? "completed" : "pending" },
    { label: "Audio", status: project.has_audio ? "completed" : "pending" },
    { label: "Configure pacing", status: "active" },
    { label: "Render", status: project.has_video ? "completed" : "pending" },
  ];

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <Link
        href={`/projects/${slug}`}
        className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
      >
        ← Back to project
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Generate Visuals
        </h1>
        <p className="mt-1 text-sm text-muted">{title}</p>
      </div>

      <div className="mb-8">
        <StepIndicator steps={steps} />
      </div>

      <VisualPacingPanel
        slug={slug}
        scenes={scenes}
        providers={providers}
        initialConfig={visualConfig}
      />
    </div>
  );
}
