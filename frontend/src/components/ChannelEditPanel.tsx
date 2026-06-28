"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import {
  updateChannelPreset,
  updateChannelVoice,
  type ChannelPreset,
  type ChannelPresetPatch,
} from "@/lib/api";
import { invalidateForChannel } from "@/lib/invalidation";
import {
  useChannelPresetQuery,
  useChannelVoiceQuery,
} from "@/lib/queries";

import { ChannelStatusBar, type SaveState } from "./ChannelStatusBar";
import { ColorSwatchPicker } from "./ColorSwatchPicker";
import { HookArchetypeSelect } from "./HookArchetypeSelect";
import { VoicePreviewButton } from "./VoicePreviewButton";
import { Row } from "./channel/Row";
import { VisualsSection } from "./channel/VisualsSection";

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
        <div className="flex items-start justify-between gap-4">
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
          <VoicePreviewButton channelId={id} />
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

