"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  createChannel,
  type ChannelCreatePayload,
  type ChannelPreset,
} from "@/lib/api";
import { invalidateForChannel } from "@/lib/invalidation";

import { ColorSwatchPicker } from "./ColorSwatchPicker";
import { HookArchetypeSelect } from "./HookArchetypeSelect";
import { StepIndicator, type WizardStep } from "./StepIndicator";
import { Row } from "./channel/Row";
import { VisualsSection } from "./channel/VisualsSection";

// Match the backend regex in channel_preset_registry._SLUG_RE so the wizard
// can disable Next at the keystroke instead of relying on a server round trip.
const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const HEX_RE = /^#[0-9a-fA-F]{6}$/;

// Default visuals shape — mirrors the backend's _build_default_visuals output
// so the wizard's step-3 form mounts with the same baseline the server would
// have written. Keeping it client-side avoids a "creating a channel" preset
// fetch that doesn't exist yet.
const DEFAULT_VISUALS: ChannelPreset["visuals"] = {
  style_description: "",
  reference_image_paths: [],
  character: { enabled: false, image_path: null, strength: 0.7 },
  creative_direction: "",
  image_prompt_model: "claude-haiku-4-5-20251001",
};

// Multi-line placeholder hint for the voice.md textarea (step 2). Shown only
// when the field is empty; populating real content with hardcoded text is
// explicitly out of scope.
const VOICE_PLACEHOLDER = `## Narrator
Describe who the narrator is...

## Audience
Describe who the viewer is...

## Voice rules
- Bullet 1
- Bullet 2
`;

const STEP_LABELS = ["Identity", "Voice", "Visuals"] as const;

type WizardState = {
  // Identity
  id: string;
  // Whether the user has hand-edited the id — once true, the auto-slug-from-
  // label suggestion stops overwriting it.
  idTouched: boolean;
  label: string;
  description: string;
  color: string;
  preferred_hook_archetype: string | null;
  // Voice
  voice_content: string;
  // Visuals
  visuals: ChannelPreset["visuals"];
};

const INITIAL_STATE: WizardState = {
  id: "",
  idTouched: false,
  label: "",
  description: "",
  color: "#4a7c3a", // first palette swatch — gives the user a sensible default
  preferred_hook_archetype: null,
  voice_content: "",
  visuals: DEFAULT_VISUALS,
};

/** Best-effort label -> slug conversion for the auto-suggest. Mirrors
 *  research_service.slugify's spirit but kept tiny and dependency-free. */
function slugifyLabel(label: string): string {
  return label
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export function ChannelCreateWizard() {
  const router = useRouter();
  const qc = useQueryClient();

  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idCollision, setIdCollision] = useState(false);

  // Indicator: step before `step` is complete, current is active, rest pending.
  const wizardSteps: WizardStep[] = useMemo(
    () =>
      STEP_LABELS.map((label, i) => ({
        label,
        status: i < step ? "completed" : i === step ? "active" : "pending",
      })),
    [step],
  );

  // Per-step validation. Used to disable Next / Create.
  const step1Valid =
    SLUG_RE.test(state.id) &&
    state.id.length >= 3 &&
    state.id.length <= 40 &&
    state.label.trim().length > 0 &&
    HEX_RE.test(state.color);
  const step2Valid = state.voice_content.trim().length > 0;
  const canAdvance = step === 0 ? step1Valid : step === 1 ? step2Valid : true;

  function update<K extends keyof WizardState>(key: K, value: WizardState[K]) {
    setState((prev) => ({ ...prev, [key]: value }));
  }

  function onLabelChange(next: string) {
    setState((prev) => ({
      ...prev,
      label: next,
      // Auto-suggest slug from label until the user has explicitly touched it.
      id: prev.idTouched ? prev.id : slugifyLabel(next),
    }));
    // Clear a stale collision warning the moment the input changes.
    if (idCollision) setIdCollision(false);
  }

  function onIdChange(next: string) {
    setState((prev) => ({ ...prev, id: next, idTouched: true }));
    if (idCollision) setIdCollision(false);
  }

  function patchVisuals(p: Partial<ChannelPreset["visuals"]>) {
    setState((prev) => ({ ...prev, visuals: { ...prev.visuals, ...p } }));
  }

  function patchCharacter(p: Partial<ChannelPreset["visuals"]["character"]>) {
    setState((prev) => ({
      ...prev,
      visuals: {
        ...prev.visuals,
        character: { ...prev.visuals.character, ...p },
      },
    }));
  }

  async function onSubmit() {
    setSubmitting(true);
    setError(null);
    setIdCollision(false);

    const payload: ChannelCreatePayload = {
      id: state.id,
      label: state.label,
      description: state.description,
      color: state.color,
      preferred_hook_archetype: state.preferred_hook_archetype,
      voice_content: state.voice_content,
      visuals: {
        style_description: state.visuals.style_description,
        reference_image_paths: state.visuals.reference_image_paths,
        creative_direction: state.visuals.creative_direction,
        image_prompt_model: state.visuals.image_prompt_model,
        character: {
          enabled: state.visuals.character.enabled,
          image_path: state.visuals.character.image_path,
          strength: state.visuals.character.strength,
        },
      },
    };

    try {
      const fresh = await createChannel(payload);
      invalidateForChannel(qc, fresh.id, router);
      router.push(`/channels/${fresh.id}`);
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 409) {
        // Bounce the user back to step 1 with an inline error on the id field.
        setIdCollision(true);
        setStep(0);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <StepIndicator steps={wizardSteps} />
      </div>

      <div>
        {step === 0 && (
          <IdentityStep
            state={state}
            onLabelChange={onLabelChange}
            onIdChange={onIdChange}
            onDescriptionChange={(v) => update("description", v)}
            onColorChange={(v) => update("color", v)}
            onHookChange={(v) => update("preferred_hook_archetype", v ?? null)}
            idCollision={idCollision}
          />
        )}
        {step === 1 && (
          <VoiceStep
            value={state.voice_content}
            onChange={(v) => update("voice_content", v)}
          />
        )}
        {step === 2 && (
          <VisualsSection
            visuals={state.visuals}
            onChangeVisuals={patchVisuals}
            onChangeCharacter={patchCharacter}
          />
        )}
      </div>

      {error && (
        <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
        <button
          type="button"
          onClick={() => setStep((s) => (s === 0 ? s : ((s - 1) as 0 | 1 | 2)))}
          disabled={step === 0 || submitting}
          className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Back
        </button>
        {step < 2 ? (
          <button
            type="button"
            onClick={() =>
              setStep((s) => (s === 2 ? s : ((s + 1) as 0 | 1 | 2)))
            }
            disabled={!canAdvance}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
          >
            Next
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting || !step1Valid || !step2Valid}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-muted"
          >
            {submitting ? "Creating..." : "Create Channel"}
          </button>
        )}
      </div>

      <style>{formInputStyle}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Identity
// ---------------------------------------------------------------------------

function IdentityStep({
  state,
  onLabelChange,
  onIdChange,
  onDescriptionChange,
  onColorChange,
  onHookChange,
  idCollision,
}: {
  state: WizardState;
  onLabelChange: (v: string) => void;
  onIdChange: (v: string) => void;
  onDescriptionChange: (v: string) => void;
  onColorChange: (v: string) => void;
  onHookChange: (v: string | undefined) => void;
  idCollision: boolean;
}) {
  const idShape =
    state.id.length === 0
      ? null
      : SLUG_RE.test(state.id) && state.id.length >= 3
        ? "ok"
        : "bad";
  return (
    <section className="rounded-xl border border-border bg-surface p-5 space-y-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-strong">
        Identity
      </h2>

      <Row label="Label" hint="Shown in dropdowns and the channels list">
        <input
          value={state.label}
          onChange={(e) => onLabelChange(e.target.value)}
          className="form-input"
          placeholder="e.g. Gardening"
          autoFocus
        />
      </Row>

      <Row
        label="Channel id"
        hint="Lowercase letters, digits, hyphens (3-40 chars). Used in folder names and prompts."
      >
        <input
          value={state.id}
          onChange={(e) => onIdChange(e.target.value)}
          className="form-input font-mono text-xs"
          placeholder="e.g. gardening"
          spellCheck={false}
        />
        {idCollision && (
          <p className="mt-1 text-xs text-danger">
            Channel id already exists, pick another.
          </p>
        )}
        {!idCollision && idShape === "bad" && (
          <p className="mt-1 text-xs text-danger">
            Must be 3-40 chars, lowercase alphanumeric + hyphens, no
            leading/trailing/doubled hyphens.
          </p>
        )}
      </Row>

      <Row label="Description" hint="One-line summary of the channel">
        <textarea
          value={state.description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          rows={2}
          className="form-input"
          placeholder="e.g. An everyday gardener channel — practical, conversational."
        />
      </Row>

      <Row label="Color" hint="Chip color on the channels list">
        <ColorSwatchPicker value={state.color} onChange={onColorChange} />
      </Row>

      <Row label="Preferred hook archetype" hint="Default opening shape">
        <HookArchetypeSelect
          value={state.preferred_hook_archetype ?? undefined}
          onChange={onHookChange}
        />
      </Row>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Voice
// ---------------------------------------------------------------------------

function VoiceStep({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-strong">
          Voice
        </h2>
        <p className="mt-1 text-xs text-muted">
          Narrator, audience, and voice-rules markdown. Spliced into the{" "}
          <span className="font-mono">{`{{CHANNEL}}`}</span> slot of every
          prompt.
        </p>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={20}
        spellCheck={false}
        placeholder={VOICE_PLACEHOLDER}
        className="form-input font-mono text-xs leading-relaxed"
      />
    </section>
  );
}

// Mirrors the inline style block in ChannelEditPanel / ScriptCreationForm so
// the .form-input class works on this page without pulling it into globals.css.
const formInputStyle = `
  .form-input {
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: var(--surface-2);
    color: var(--foreground);
    border: 1px solid var(--border);
    border-radius: 0.375rem;
    font-size: 0.875rem;
    outline: none;
    transition: border-color 0.15s;
  }
  .form-input:focus { border-color: var(--accent); }
  .form-input:disabled { opacity: 0.6; cursor: not-allowed; }
`;
