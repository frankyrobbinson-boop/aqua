"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import {
  getVisualPromptModels,
  updateChannelPreset,
  updateChannelVoice,
  type ChannelPreset,
  type ChannelPresetPatch,
  type VisualPromptModel,
} from "@/lib/api";
import { invalidateForChannel } from "@/lib/invalidation";
import {
  useChannelPresetQuery,
  useChannelVoiceQuery,
} from "@/lib/queries";

import { ChannelStatusBar, type SaveState } from "./ChannelStatusBar";
import { ColorSwatchPicker } from "./ColorSwatchPicker";
import { HookArchetypeSelect } from "./HookArchetypeSelect";

const SAVE_DEBOUNCE_MS = 600;

type Props = { id: string };

/**
 * Read-write editor for a channel preset (Phase 3b). Owns local state for
 * the editable fields and runs two independent debounced autosaves — one
 * for preset.json (PATCH-style partial), one for voice.md (full content).
 *
 * Layout (top-to-bottom): Identity → Voice → Visuals. Each section computes
 * its own patch and feeds the same shared SaveState indicator at the top.
 */
export function ChannelEditPanel({ id }: Props) {
  const router = useRouter();
  const qc = useQueryClient();

  const presetQuery = useChannelPresetQuery(id);
  const voiceQuery = useChannelVoiceQuery(id);

  if (presetQuery.isLoading || voiceQuery.isLoading) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface/40 p-12 text-center text-sm text-muted">
        Loading channel...
      </div>
    );
  }
  if (presetQuery.error || !presetQuery.data) {
    return (
      <div className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        Could not load channel preset:{" "}
        {presetQuery.error instanceof Error
          ? presetQuery.error.message
          : "unknown error"}
      </div>
    );
  }
  if (voiceQuery.error || !voiceQuery.data) {
    return (
      <div className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        Could not load voice.md:{" "}
        {voiceQuery.error instanceof Error
          ? voiceQuery.error.message
          : "unknown error"}
      </div>
    );
  }

  return (
    <EditorBody
      id={id}
      initialPreset={presetQuery.data}
      initialVoice={voiceQuery.data.content}
      onSaved={() => invalidateForChannel(qc, id, router)}
    />
  );
}

function EditorBody({
  id,
  initialPreset,
  initialVoice,
  onSaved,
}: {
  id: string;
  initialPreset: ChannelPreset;
  initialVoice: string;
  onSaved: () => void;
}) {
  const [preset, setPreset] = useState<ChannelPreset>(initialPreset);
  const [voice, setVoice] = useState<string>(initialVoice);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });

  // Track which subsystems have an unflushed change. We start "idle" and only
  // flip to "saving" after the user edits — never on mount.
  const skipPresetSave = useRef(true);
  const skipVoiceSave = useRef(true);

  // ----- Debounced autosave: preset.json -------------------------------------
  // We build the patch from local state diffed against the last successfully
  // saved snapshot. Sending the whole object would be fine (backend deep-
  // merges) but a minimal patch makes the wire/log readable.
  const lastSavedPreset = useRef<ChannelPreset>(initialPreset);

  useEffect(() => {
    if (skipPresetSave.current) {
      skipPresetSave.current = false;
      return;
    }
    setSaveState({ kind: "saving" });
    const handle = setTimeout(() => {
      const patch = diffPreset(lastSavedPreset.current, preset);
      if (Object.keys(patch).length === 0) {
        setSaveState({ kind: "saved", at: Date.now() });
        return;
      }
      updateChannelPreset(id, patch)
        .then((fresh) => {
          lastSavedPreset.current = fresh;
          setSaveState({ kind: "saved", at: Date.now() });
          onSaved();
        })
        .catch((err) => {
          setSaveState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [preset, id, onSaved]);

  // ----- Debounced autosave: voice.md ----------------------------------------
  useEffect(() => {
    if (skipVoiceSave.current) {
      skipVoiceSave.current = false;
      return;
    }
    setSaveState({ kind: "saving" });
    const handle = setTimeout(() => {
      updateChannelVoice(id, voice)
        .then(() => {
          setSaveState({ kind: "saved", at: Date.now() });
          onSaved();
        })
        .catch((err) => {
          setSaveState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [voice, id, onSaved]);

  function patchVisuals(p: Partial<ChannelPreset["visuals"]>) {
    setPreset((prev) => ({ ...prev, visuals: { ...prev.visuals, ...p } }));
  }

  function patchCharacter(p: Partial<ChannelPreset["visuals"]["character"]>) {
    setPreset((prev) => ({
      ...prev,
      visuals: {
        ...prev.visuals,
        character: { ...prev.visuals.character, ...p },
      },
    }));
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          Channel id: <span className="font-mono">{preset.id}</span>
        </p>
        <ChannelStatusBar state={saveState} />
      </div>

      {/* ----- Identity --------------------------------------------------- */}
      <section className="rounded-xl border border-border bg-surface p-5 space-y-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-strong">
          Identity
        </h2>

        <Row label="Label" hint="Shown in dropdowns and the channels list">
          <input
            value={preset.label}
            onChange={(e) => setPreset((p) => ({ ...p, label: e.target.value }))}
            className="form-input"
          />
        </Row>

        <Row label="Description" hint="One-line summary of the channel">
          <textarea
            value={preset.description}
            onChange={(e) =>
              setPreset((p) => ({ ...p, description: e.target.value }))
            }
            rows={2}
            className="form-input"
          />
        </Row>

        <Row label="Color" hint="Chip color on the channels list">
          <ColorSwatchPicker
            value={preset.color}
            onChange={(hex) => setPreset((p) => ({ ...p, color: hex }))}
          />
        </Row>

        <Row label="Preferred hook archetype" hint="Default opening shape">
          <HookArchetypeSelect
            value={preset.preferred_hook_archetype ?? undefined}
            onChange={(next) =>
              setPreset((p) => ({
                ...p,
                preferred_hook_archetype: next ?? null,
              }))
            }
          />
        </Row>
      </section>

      {/* ----- Voice ------------------------------------------------------ */}
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
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          rows={20}
          spellCheck={false}
          className="form-input font-mono text-xs leading-relaxed"
        />
      </section>

      {/* ----- Visuals ---------------------------------------------------- */}
      <VisualsSection
        visuals={preset.visuals}
        onChangeVisuals={patchVisuals}
        onChangeCharacter={patchCharacter}
      />

      <style>{formInputStyle}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visuals subsection — split to keep EditorBody readable.
// ---------------------------------------------------------------------------

function VisualsSection({
  visuals,
  onChangeVisuals,
  onChangeCharacter,
}: {
  visuals: ChannelPreset["visuals"];
  onChangeVisuals: (p: Partial<ChannelPreset["visuals"]>) => void;
  onChangeCharacter: (
    p: Partial<ChannelPreset["visuals"]["character"]>,
  ) => void;
}) {
  const [models, setModels] = useState<VisualPromptModel[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVisualPromptModels()
      .then((res) => {
        if (!cancelled) setModels(res.models);
      })
      .catch((err) => {
        if (!cancelled) {
          setModelsError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const charDisabled = !visuals.character.enabled;

  return (
    <section className="rounded-xl border border-border bg-surface p-5 space-y-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-strong">
        Visuals
      </h2>

      <Row
        label="Style description"
        hint="Visual style for every AI image (e.g. 'painterly, soft natural light')"
      >
        <textarea
          value={visuals.style_description}
          onChange={(e) => onChangeVisuals({ style_description: e.target.value })}
          rows={3}
          className="form-input"
          placeholder="e.g. painterly, warm natural light, shallow depth of field"
        />
      </Row>

      <Row
        label="Creative direction"
        hint="Free-form notes the prompt enhancer should respect"
      >
        <textarea
          value={visuals.creative_direction}
          onChange={(e) =>
            onChangeVisuals({ creative_direction: e.target.value })
          }
          rows={3}
          className="form-input"
          placeholder="e.g. Always show the gardener from behind; avoid stock-photo poses."
        />
      </Row>

      <Row
        label="Reference image paths"
        hint="One file path per line — referenced by the prompt enhancer"
      >
        <textarea
          value={visuals.reference_image_paths.join("\n")}
          onChange={(e) =>
            onChangeVisuals({
              reference_image_paths: e.target.value
                .split("\n")
                .map((s) => s.trim())
                .filter((s) => s.length > 0),
            })
          }
          rows={3}
          spellCheck={false}
          className="form-input font-mono text-xs"
          placeholder="prompts/channels/gardening/refs/style-1.jpg"
        />
      </Row>

      <Row label="Image prompt model" hint="Which model styles each scene's prompt">
        <select
          value={visuals.image_prompt_model}
          onChange={(e) => onChangeVisuals({ image_prompt_model: e.target.value })}
          className="form-input"
          disabled={models.length === 0}
        >
          {models.length === 0 && (
            <option value={visuals.image_prompt_model}>
              {visuals.image_prompt_model || "Loading..."}
            </option>
          )}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label} (~${m.cost_per_video_estimate.toFixed(2)}/video)
            </option>
          ))}
        </select>
        {modelsError && (
          <p className="mt-1 text-xs text-danger">{modelsError}</p>
        )}
      </Row>

      {/* ----- Character ---------------------------------------------------- */}
      <div className="rounded-lg border border-border bg-surface/40 p-4 space-y-4">
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-foreground">
              Recurring character
            </span>
            <p className="mt-0.5 text-xs text-muted">
              When on, the prompt enhancer biases scenes toward a single
              consistent subject.
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              onChangeCharacter({ enabled: !visuals.character.enabled })
            }
            aria-pressed={visuals.character.enabled}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              visuals.character.enabled ? "bg-accent" : "bg-surface-3"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                visuals.character.enabled ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </label>

        <Row
          label="Character image path"
          hint="Reference photo of the character (file path)"
        >
          <input
            value={visuals.character.image_path ?? ""}
            onChange={(e) =>
              onChangeCharacter({ image_path: e.target.value || null })
            }
            disabled={charDisabled}
            spellCheck={false}
            className="form-input font-mono text-xs"
            placeholder="prompts/channels/gardening/character.jpg"
          />
        </Row>

        <Row
          label="Character strength"
          hint={`${visuals.character.strength.toFixed(2)} — how strongly the model adheres to the reference`}
        >
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={visuals.character.strength}
            onChange={(e) =>
              onChangeCharacter({ strength: Number(e.target.value) })
            }
            disabled={charDisabled}
            className="w-full accent-accent disabled:opacity-50"
          />
        </Row>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal patch builder: returns the keys (and nested visuals/character
 *  fields) that changed between snapshots. Avoids PUTting the whole preset
 *  on every keystroke so request logs stay readable. */
function diffPreset(
  prev: ChannelPreset,
  next: ChannelPreset,
): ChannelPresetPatch {
  const patch: ChannelPresetPatch = {};
  if (prev.label !== next.label) patch.label = next.label;
  if (prev.description !== next.description) patch.description = next.description;
  if (prev.color !== next.color) patch.color = next.color;
  if (prev.preferred_hook_archetype !== next.preferred_hook_archetype) {
    // null is a valid value; the backend allows it via Optional[str].
    if (next.preferred_hook_archetype !== null) {
      patch.preferred_hook_archetype = next.preferred_hook_archetype;
    }
  }

  const v = diffVisuals(prev.visuals, next.visuals);
  if (v) patch.visuals = v;
  return patch;
}

function diffVisuals(
  prev: ChannelPreset["visuals"],
  next: ChannelPreset["visuals"],
): ChannelPresetPatch["visuals"] | null {
  const out: NonNullable<ChannelPresetPatch["visuals"]> = {};
  if (prev.style_description !== next.style_description) {
    out.style_description = next.style_description;
  }
  if (prev.creative_direction !== next.creative_direction) {
    out.creative_direction = next.creative_direction;
  }
  if (prev.image_prompt_model !== next.image_prompt_model) {
    out.image_prompt_model = next.image_prompt_model;
  }
  if (!arraysEqual(prev.reference_image_paths, next.reference_image_paths)) {
    out.reference_image_paths = next.reference_image_paths;
  }
  const character: Partial<ChannelPreset["visuals"]["character"]> = {};
  if (prev.character.enabled !== next.character.enabled) {
    character.enabled = next.character.enabled;
  }
  if (prev.character.image_path !== next.character.image_path) {
    // Null is a meaningful value (clears the field) — send it through.
    character.image_path = next.character.image_path;
  }
  if (prev.character.strength !== next.character.strength) {
    character.strength = next.character.strength;
  }
  if (Object.keys(character).length > 0) out.character = character;
  return Object.keys(out).length === 0 ? null : out;
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  // Memoize-able trivial wrapper — same shape as ScriptCreationForm's Row.
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

// Mirrors the inline style block in ScriptCreationForm so the .form-input
// class works on this page without pulling it into globals.css.
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

