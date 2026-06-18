"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ScriptCreationForm } from "./ScriptCreationForm";
import { StageRunner } from "./StageRunner";
import { Stepper, type Step } from "./Stepper";
import {
  API_URL,
  projectFileUrl,
  updateScript,
  type ProjectDetail,
  type SceneInfo,
  type ScriptDraft,
  type TaskStatus,
} from "@/lib/api";

type Props = {
  slug: string;
  project: ProjectDetail;
  scenes: SceneInfo[];
};

function pickDefaultStep(project: ProjectDetail): Step {
  if (project.has_video) return 4;
  if (project.has_audio) return 3;
  if (project.has_script) return 2;
  return 1;
}

export function ProjectView({ slug, project, scenes }: Props) {
  const [step, setStep] = useState<Step>(() => pickDefaultStep(project));

  const completed = new Set<Step>();
  if (project.has_script) completed.add(1);
  if (project.has_audio) completed.add(2);
  const withFootage = scenes.filter((s) => s.has_footage).length;
  if (scenes.length > 0 && withFootage === scenes.length) completed.add(3);
  if (project.has_video) completed.add(4);

  const disabled = new Set<Step>();
  if (!project.has_script) {
    disabled.add(2);
    disabled.add(3);
    disabled.add(4);
  } else if (!project.has_audio) {
    disabled.add(3);
    disabled.add(4);
  }

  return (
    <>
      <Stepper
        current={step}
        completed={completed}
        disabled={disabled}
        onSelect={(n) => setStep(n)}
      />

      {step === 1 && (
        <ScriptTab slug={slug} script={project.script_draft} />
      )}
      {step === 2 && (
        <VoiceoverTab slug={slug} project={project} sceneCount={scenes.length} />
      )}
      {step === 3 && <VisualsTab slug={slug} scenes={scenes} />}
      {step === 4 && (
        <RenderTab slug={slug} project={project} scenes={scenes} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Script
// ---------------------------------------------------------------------------

function ScriptTab({
  slug,
  script,
}: {
  slug: string;
  script: ScriptDraft | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);

  if (!script) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6">
        <h2 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
          Configure script
        </h2>
        <p className="mb-6 text-sm text-muted">
          Fill in the topic and any context, then generate the script.
        </p>
        <ScriptCreationForm
          projectSlug={slug}
          onRunComplete={(_slug, status) => {
            if (status === "completed") router.refresh();
          }}
        />
      </section>
    );
  }

  if (editing) {
    return (
      <ScriptEditor
        slug={slug}
        initial={script}
        onDone={() => setEditing(false)}
      />
    );
  }

  return <ScriptViewer script={script} onEdit={() => setEditing(true)} />;
}

function ScriptViewer({
  script,
  onEdit,
}: {
  script: ScriptDraft;
  onEdit: () => void;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h2 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
            Script
          </h2>
          <h3 className="text-xl font-semibold text-foreground">
            {script.title}
          </h3>
        </div>
        <button
          type="button"
          onClick={onEdit}
          className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-3"
        >
          Edit script
        </button>
      </div>

      <ScriptBlock label="Hook" body={script.hook.narration} />

      {script.segments.map((seg, i) => (
        <ScriptBlock
          key={i}
          label={`Segment ${i + 1}: ${seg.title}`}
          body={seg.narration}
          note={seg.visual_notes}
        />
      ))}

      <ScriptBlock
        label="Conclusion"
        body={script.conclusion.narration}
        note={`CTA: ${script.conclusion.cta}`}
      />
    </section>
  );
}

function ScriptEditor({
  slug,
  initial,
  onDone,
}: {
  slug: string;
  initial: ScriptDraft;
  onDone: () => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<ScriptDraft>(() =>
    structuredClone(initial),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSave() {
    setError(null);
    setSaving(true);
    try {
      await updateScript(slug, draft);
      router.refresh();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex-1">
          <h2 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
            Edit script
          </h2>
          <input
            value={draft.title}
            onChange={(e) =>
              setDraft({ ...draft, title: e.target.value })
            }
            className="w-full bg-transparent text-xl font-semibold text-foreground outline-none focus:bg-surface-2 px-1 rounded"
          />
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onDone}
            disabled={saving}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-muted-strong hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
          {error}
        </div>
      )}

      <div className="mb-4 rounded-md border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
        Saving deletes the voiceover audio, scene plan, footage, and rendered
        video so they regenerate against your edits — you&apos;ll need to re-run
        the downstream stages. ElevenLabs caches per-chunk by content, so only
        chunks whose text actually changed will be re-billed.
      </div>

      <ScriptEditBlock
        label="Hook"
        body={draft.hook.narration}
        onChange={(narration) =>
          setDraft({ ...draft, hook: { ...draft.hook, narration } })
        }
      />

      {draft.segments.map((seg, i) => (
        <div key={i} className="mb-6 border-l-2 border-border pl-4">
          <input
            value={seg.title}
            onChange={(e) => {
              const segments = [...draft.segments];
              segments[i] = { ...seg, title: e.target.value };
              setDraft({ ...draft, segments });
            }}
            placeholder="Segment title"
            className="mb-1 w-full bg-transparent text-sm font-semibold text-foreground outline-none focus:bg-surface-2 px-1 rounded"
          />
          <input
            value={seg.visual_notes}
            onChange={(e) => {
              const segments = [...draft.segments];
              segments[i] = { ...seg, visual_notes: e.target.value };
              setDraft({ ...draft, segments });
            }}
            placeholder="Visual notes"
            className="mb-2 w-full bg-transparent text-xs italic text-muted outline-none focus:bg-surface-2 px-1 rounded"
          />
          <textarea
            value={seg.narration}
            onChange={(e) => {
              const segments = [...draft.segments];
              segments[i] = { ...seg, narration: e.target.value };
              setDraft({ ...draft, segments });
            }}
            rows={Math.max(4, Math.ceil(seg.narration.length / 90))}
            className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-foreground outline-none focus:border-accent"
          />
          <p className="mt-1 text-xs text-muted">
            {seg.narration.trim().split(/\s+/).filter(Boolean).length} words
          </p>
        </div>
      ))}

      <ScriptEditBlock
        label="Conclusion"
        body={draft.conclusion.narration}
        onChange={(narration) =>
          setDraft({
            ...draft,
            conclusion: { ...draft.conclusion, narration },
          })
        }
      />

      <div className="mt-2 border-l-2 border-border pl-4">
        <p className="mb-1 text-xs font-semibold text-foreground">CTA</p>
        <input
          value={draft.conclusion.cta}
          onChange={(e) =>
            setDraft({
              ...draft,
              conclusion: { ...draft.conclusion, cta: e.target.value },
            })
          }
          className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-foreground outline-none focus:border-accent"
        />
      </div>
    </section>
  );
}

function ScriptEditBlock({
  label,
  body,
  onChange,
}: {
  label: string;
  body: string;
  onChange: (next: string) => void;
}) {
  const wordCount = body.trim().split(/\s+/).filter(Boolean).length;
  return (
    <div className="mb-6 border-l-2 border-border pl-4">
      <div className="mb-1 flex items-center gap-2">
        <p className="text-sm font-semibold text-foreground">{label}</p>
        <span className="text-xs text-muted">({wordCount} words)</span>
      </div>
      <textarea
        value={body}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.max(3, Math.ceil(body.length / 90))}
        className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-foreground outline-none focus:border-accent"
      />
    </div>
  );
}

function ScriptBlock({
  label,
  body,
  note,
}: {
  label: string;
  body: string;
  note?: string;
}) {
  const wordCount = body.trim().split(/\s+/).filter(Boolean).length;
  return (
    <div className="mb-6 border-l-2 border-border pl-4">
      <div className="mb-1 flex items-center gap-2">
        <h4 className="text-sm font-semibold text-foreground">{label}</h4>
        <span className="text-xs text-muted">({wordCount} words)</span>
      </div>
      {note && <p className="mb-2 text-xs italic text-muted">{note}</p>}
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-strong">
        {body}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Voiceover
// ---------------------------------------------------------------------------

function VoiceoverTab({
  slug,
  project,
  sceneCount,
}: {
  slug: string;
  project: ProjectDetail;
  sceneCount: number;
}) {
  const [voiceSpeed, setVoiceSpeed] = useState<number>(1.0);
  const audioUrl = project.has_audio
    ? projectFileUrl(slug, "video/full_audio.mp3")
    : null;

  const wordCount = project.script_draft
    ? [
        project.script_draft.hook.narration,
        ...project.script_draft.segments.map((s) => s.narration),
        project.script_draft.conclusion.narration,
      ]
        .join(" ")
        .split(/\s+/)
        .filter(Boolean).length
    : 0;

  return (
    <div className="space-y-6">
      {audioUrl ? (
        <section className="rounded-xl border border-border bg-surface p-5">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
            Voiceover
          </p>
          <audio src={audioUrl} controls className="w-full" />
          {sceneCount > 0 && (
            <p className="mt-3 text-xs text-muted">
              {sceneCount} scenes planned
            </p>
          )}
        </section>
      ) : (
        <EmptyTab>No voiceover yet — kick off the generation below.</EmptyTab>
      )}

      <VoiceoverConfigPanel
        voiceSpeed={voiceSpeed}
        setVoiceSpeed={setVoiceSpeed}
      />

      <section className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium text-foreground">
          {project.has_audio ? "Regenerate voiceover" : "Generate voiceover"}
        </h2>
        <ol className="mb-4 space-y-1 text-sm text-muted-strong">
          <li>1. TTS prep — expand numbers, add break tags from your latest script</li>
          <li>2. Voice prep — chunk for ElevenLabs</li>
          <li>3. Delivery plan — annotate pacing</li>
          <li>4. Audio generation — render {wordCount.toLocaleString()} words at {voiceSpeed.toFixed(2)}x</li>
        </ol>
        <p className="mb-4 text-xs text-muted">
          ElevenLabs charges by character — roughly $2–3 for a 10-minute script.
        </p>
        <StageRunner stage="voiceover" slug={slug} voiceSpeed={voiceSpeed} />
      </section>
    </div>
  );
}

function VoiceoverConfigPanel({
  voiceSpeed,
  setVoiceSpeed,
}: {
  voiceSpeed: number;
  setVoiceSpeed: (n: number) => void;
}) {
  return (
    <ConfigPanel title="Voice settings" badge="speed wired">
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigRow label="Provider" hint="More coming">
          <select className="config-select" disabled value="elevenlabs">
            <option value="elevenlabs">ElevenLabs</option>
          </select>
        </ConfigRow>
        <ConfigRow label="Model" hint="Coming">
          <select className="config-select" disabled value="multilingual-v2">
            <option>Multilingual v2</option>
          </select>
        </ConfigRow>
      </div>
      <ConfigRow label="Voice" hint="Inherits from .env">
        <input
          placeholder="Paste an ElevenLabs voice ID..."
          className="config-select font-mono text-xs"
          disabled
        />
      </ConfigRow>
      <div className="flex flex-col gap-1.5">
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <label className="text-sm font-medium text-foreground">Speed</label>
          <span className="text-xs text-muted">
            Native ElevenLabs `speed` setting
          </span>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0.8}
            max={1.2}
            step={0.05}
            value={voiceSpeed}
            onChange={(e) => setVoiceSpeed(Number(e.target.value))}
            className="flex-1 accent-accent"
          />
          <span className="w-16 text-right text-sm font-medium tabular-nums text-foreground">
            {voiceSpeed.toFixed(2)}x
          </span>
        </div>
      </div>
      <InfoBox>
        <strong className="text-foreground">Already on:</strong> loudness
        normalization (−16 LUFS), peak limiter at −1.0 dB, end-of-chunk artifact
        trim (30 ms), chunk stitching for prosody continuity.
      </InfoBox>
    </ConfigPanel>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Visuals
// ---------------------------------------------------------------------------

function VisualsTab({ slug, scenes }: { slug: string; scenes: SceneInfo[] }) {
  const total = scenes.length;
  const withFootage = scenes.filter((s) => s.has_footage).length;
  const hasScenes = total > 0;
  const fullyCovered = hasScenes && withFootage === total;

  return (
    <div className="space-y-6">
      {hasScenes && (
        <section className="rounded-xl border border-border bg-surface p-5">
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-medium text-foreground">{total} scenes</h2>
            <span className="text-xs text-muted">
              {withFootage} / {total} have footage
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full bg-success transition-all"
              style={{ width: `${total ? (withFootage / total) * 100 : 0}%` }}
            />
          </div>
        </section>
      )}

      <VisualsConfigPanel />

      <section className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium text-foreground">
          {!hasScenes
            ? "Generate visuals"
            : fullyCovered
              ? "Refetch footage"
              : "Fetch footage"}
        </h2>
        <p className="mb-4 text-xs text-muted">
          {!hasScenes
            ? "Plans the scenes from the script, computes their timing against the voiceover, then fetches Pexels footage for each one."
            : "Pexels search per scene. Cached clips skip download."}
        </p>
        <StageRunner stage="visuals" slug={slug} />
      </section>

      {hasScenes && (
        <section>
          <h2 className="mb-4 text-sm font-medium text-foreground">Scenes</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {scenes.map((scene) => (
              <SceneCard key={scene.id} scene={scene} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function VisualsConfigPanel() {
  return (
    <ConfigPanel title="Visual settings" badge="placeholders">
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigRow label="Provider" hint="Stock only for now">
          <select className="config-select" disabled value="pexels">
            <option value="pexels">Pexels (stock)</option>
          </select>
        </ConfigRow>
        <ConfigRow label="AI fallback" hint="Coming">
          <select className="config-select" disabled value="none">
            <option value="none">None — stock only</option>
          </select>
        </ConfigRow>
      </div>
      <ConfigRow label="Scene granularity" hint="8–15s default">
        <select className="config-select" disabled value="default">
          <option value="default">Default (40–60 scenes per 10 min)</option>
        </select>
      </ConfigRow>
      <InfoBox>
        <strong className="text-foreground">Already on:</strong> Claude Haiku
        LLM rerank · respects Pexels relevance order · topic-anchored search
        queries.
      </InfoBox>
    </ConfigPanel>
  );
}

function SceneCard({ scene }: { scene: SceneInfo }) {
  const videoUrl = scene.footage_url ? `${API_URL}${scene.footage_url}` : null;
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="relative aspect-video bg-background">
        {videoUrl ? (
          <video
            src={videoUrl}
            muted
            playsInline
            preload="metadata"
            controls
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-muted">
            No footage
          </div>
        )}
        <span className="absolute left-2 top-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-xs text-muted">
          #{scene.id}
        </span>
        {scene.duration != null && (
          <span className="absolute right-2 top-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-xs text-muted">
            {scene.duration.toFixed(1)}s
          </span>
        )}
      </div>
      <div className="p-3">
        <p className="line-clamp-2 text-xs font-medium text-foreground">
          {scene.visual_description || "(no query)"}
        </p>
        <p className="mt-1 line-clamp-2 text-xs text-muted">{scene.narration}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Render
// ---------------------------------------------------------------------------

function RenderTab({
  slug,
  project,
  scenes,
}: {
  slug: string;
  project: ProjectDetail;
  scenes: SceneInfo[];
}) {
  const videoUrl = project.has_video
    ? projectFileUrl(slug, "video/final.mp4")
    : null;
  const sceneCount = scenes.length;
  const withFootage = scenes.filter((s) => s.has_footage).length;
  const canRender = sceneCount > 0 && withFootage === sceneCount;

  return (
    <div className="space-y-6">
      {videoUrl ? (
        <section className="overflow-hidden rounded-xl border border-border bg-surface">
          <video src={videoUrl} controls className="aspect-video w-full bg-black" />
        </section>
      ) : (
        <EmptyTab>No render yet — fetch footage, then render below.</EmptyTab>
      )}

      <RenderConfigPanel />

      {!canRender && sceneCount > 0 && (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
          {sceneCount - withFootage} scenes still need footage. Switch to the
          Visuals tab to fetch them.
        </div>
      )}

      <section className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium text-foreground">
          {project.has_video ? "Re-render video" : "Render video"}
        </h2>
        <p className="mb-4 text-xs text-muted">
          Normalize clips, concat with voiceover, burn in subtitles. ~15–20 min
          for a 10-minute video.
        </p>
        <StageRunner stage="render" slug={slug} disabled={!canRender} />
      </section>
    </div>
  );
}

function RenderConfigPanel() {
  return (
    <ConfigPanel title="Render settings" badge="placeholders">
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigRow label="Resolution" hint="1080p locked">
          <div className="flex gap-1">
            {["720p", "1080p"].map((r) => (
              <button
                key={r}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  r === "1080p"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </ConfigRow>
        <ConfigRow label="Frame rate" hint="25 fps locked">
          <div className="flex gap-1">
            {["24", "25", "30"].map((f) => (
              <button
                key={f}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  f === "25"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {f} fps
              </button>
            ))}
          </div>
        </ConfigRow>
      </div>
      <PlaceholderToggle
        label="Subtitles"
        checked
        hint="Word-level highlight, burned in"
      />
      <PlaceholderToggle
        label="Background music"
        checked={false}
        hint="Upload + ducking — coming"
      />
      <ConfigRow label="Scene transition" hint="Hard cuts">
        <select className="config-select" disabled value="cut">
          <option value="cut">Hard cut</option>
        </select>
      </ConfigRow>
      <InfoBox>
        <strong className="text-foreground">Render pipeline:</strong> libx264 ·
        CRF 18 · scale+crop · libass subtitle burn-in · AAC audio mux.
      </InfoBox>
    </ConfigPanel>
  );
}

// ---------------------------------------------------------------------------
// Shared placeholder UI for stage config panels
// ---------------------------------------------------------------------------

function ConfigPanel({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-foreground">{title}</h2>
        {badge && (
          <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs text-muted">
            {badge}
          </span>
        )}
      </div>
      <div className="space-y-4">{children}</div>
      <style>{`
        .config-select {
          width: 100%;
          padding: 0.5rem 0.75rem;
          background: var(--surface-2);
          color: var(--foreground);
          border: 1px solid var(--border);
          border-radius: 0.375rem;
          font-size: 0.875rem;
          outline: none;
        }
        .config-select:disabled { opacity: 0.6; cursor: not-allowed; }
      `}</style>
    </section>
  );
}

function ConfigRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="opacity-70">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function PlaceholderToggle({
  label,
  checked,
  hint,
}: {
  label: string;
  checked: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 opacity-70">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        {hint && <p className="text-xs text-muted">{hint}</p>}
      </div>
      <button
        type="button"
        disabled
        className={`relative inline-flex h-6 w-11 cursor-not-allowed items-center rounded-full ${
          checked ? "bg-accent" : "bg-surface-3"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

function InfoBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 p-3 text-xs text-muted">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------

function EmptyTab({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface/40 p-12 text-center text-sm text-muted">
      {children}
    </div>
  );
}
