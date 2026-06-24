"use client";

import { useEffect, useState } from "react";

import {
  getVisualPromptModels,
  type ChannelPreset,
  type VisualPromptModel,
} from "@/lib/api";

import { Row } from "./Row";

/**
 * Channel-visuals editor — the same shape used by both the Phase 3b inline
 * editor (`ChannelEditPanel`) and the Phase 3c create-channel wizard. Pure
 * presentational; the parent owns the visuals slice of state and reacts to
 * `onChangeVisuals` / `onChangeCharacter` patches.
 *
 * Fetches the prompt-model registry on mount because the dropdown options
 * depend on it; that fetch is local because both consumers want it and the
 * payload is tiny (5-line JSON). Cancelling on unmount avoids a setState on
 * an unmounted component when the user navigates away mid-flight.
 */
export function VisualsSection({
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
