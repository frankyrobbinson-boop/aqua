/** Thin client for the Aqua FastAPI service. */

// Type-only imports: erased at compile time, so this stays a pure client with no
// runtime dependency on the Remotion bundle. Used by startRemotionRender +
// the transition-design helpers.
import type { CardProps } from "@/remotion/cards/types";
import type { TransitionParams } from "@/remotion/transitions/registry";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** URL for a static file inside a project (video, audio, image). */
export function projectFileUrl(slug: string, relativePath: string): string {
  return `${API_URL}/files/${encodeURIComponent(slug)}/${relativePath}`;
}

export type ProjectSummary = {
  slug: string;
  title: string;
  has_script: boolean;
  has_audio: boolean;
  has_video: boolean;
  modified_at: number;
};

export type ScriptDraft = {
  title: string;
  title_spoken: string;
  item_noun: string;
  hook: { narration: string };
  segments: Array<{
    title: string;
    narration: string;
    visual_notes: string;
  }>;
  conclusion: { narration: string };
};

export type ProjectDetail = ProjectSummary & {
  research: { topic: string; research: string } | null;
  outline: unknown;
  script_draft: ScriptDraft | null;
  tts_script: ScriptDraft | null;
  scene_plan: unknown;
  audio_timeline: unknown;
  scene_windows: unknown;
};

export type ScriptRequest = {
  topic: string;
  target_minutes: number;
  /** If set, write artifacts into this existing project slug (resume a draft
   *  or re-run script for an existing project). When omitted, the backend
   *  derives a unique slug from the topic. */
  project_slug?: string;
  /** Selects the outline/script structure module from video_types.json. */
  video_type?: string;
  /** Number of items per section-list (3–12). Applies to list video types. */
  item_count?: number;
  hook_archetype?: string;
  /** ElevenLabs voice speed (0.8–1.2). 1.0 = native rate. */
  voice_speed?: number;
  /** Notes / list / context to seed the GPT-5 research prompt. */
  pre_research?: string;
  additional_instructions?: string;
  sample_script?: string;
  channel?: string;
};

export type VideoType = {
  id: string;
  label: string;
  description: string;
};

export type VideoTypesResponse = {
  default_type: string;
  types: VideoType[];
};

export async function getVideoTypes(): Promise<VideoTypesResponse> {
  return getJSON<VideoTypesResponse>("/video-types");
}

export type HookArchetype = {
  id: string;
  label: string;
  description: string;
};

export type HookArchetypesResponse = {
  default_archetype: string;
  archetypes: HookArchetype[];
};

export async function getHookArchetypes(): Promise<HookArchetypesResponse> {
  return getJSON<HookArchetypesResponse>("/hook-archetypes");
}

export type Channel = {
  id: string;
  name: string;
  description: string;
  color: string;
};

export type ChannelsResponse = {
  default_channel: string;
  channels: Channel[];
};

export type ChannelDetail = {
  id: string;
  name: string;
  description: string;
  preferred_hook_archetype: string | null;
  preferred_hook_archetype_label: string | null;
  sections: Record<string, string>;
};

export async function getChannels(): Promise<ChannelsResponse> {
  return getJSON<ChannelsResponse>("/channels");
}

export async function getChannel(id: string): Promise<ChannelDetail> {
  return getJSON<ChannelDetail>(`/channels/${encodeURIComponent(id)}`);
}

// ---------------------------------------------------------------------------
// Channel preset (Phase 3b editor) — distinct from the legacy ChannelDetail
// above. The editor reads preset.json + voice.md directly so it can write
// them back; dropdown consumers stick with getChannel().
// ---------------------------------------------------------------------------

export type ChannelPresetCharacter = {
  enabled: boolean;
  image_path: string | null;
  strength: number;
};

export type ChannelPresetVisuals = {
  style_description: string;
  reference_image_paths: string[];
  character: ChannelPresetCharacter;
  creative_direction: string;
  image_prompt_model: string;
};

export type ChannelPreset = {
  id: string;
  label: string;
  description: string;
  color: string;
  preferred_hook_archetype: string | null;
  visuals: ChannelPresetVisuals;
};

/** Partial update — every leaf optional. Matches ChannelPresetPatch in
 *  backend/api/routes/scripts.py. */
export type ChannelPresetPatch = {
  label?: string;
  description?: string;
  color?: string;
  preferred_hook_archetype?: string;
  visuals?: {
    style_description?: string;
    reference_image_paths?: string[];
    character?: Partial<ChannelPresetCharacter>;
    creative_direction?: string;
    image_prompt_model?: string;
  };
};

export async function getChannelPreset(id: string): Promise<ChannelPreset> {
  return getJSON<ChannelPreset>(`/channels/${encodeURIComponent(id)}/preset`);
}

export async function updateChannelPreset(
  id: string,
  patch: ChannelPresetPatch,
): Promise<ChannelPreset> {
  const res = await fetch(
    `${API_URL}/channels/${encodeURIComponent(id)}/preset`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Update channel preset failed: ${res.status} ${text || res.statusText}`,
    );
  }
  return res.json() as Promise<ChannelPreset>;
}

/** Body for POST /channels (Phase 3c create-channel wizard). Mirrors
 *  ChannelCreatePayload in backend/api/routes/scripts.py. */
export type ChannelCreatePayload = {
  id: string;
  label: string;
  description: string;
  color: string;
  preferred_hook_archetype: string | null;
  voice_content: string;
  visuals?: ChannelPresetPatch["visuals"];
};

export async function createChannel(
  payload: ChannelCreatePayload,
): Promise<ChannelPreset> {
  const res = await fetch(`${API_URL}/channels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    // Surface the status so callers (the wizard) can branch on 409.
    const err = new Error(
      `Create channel failed: ${res.status} ${text || res.statusText}`,
    ) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<ChannelPreset>;
}

export async function getChannelVoice(id: string): Promise<{ content: string }> {
  return getJSON<{ content: string }>(
    `/channels/${encodeURIComponent(id)}/voice`,
  );
}

export async function updateChannelVoice(
  id: string,
  content: string,
): Promise<void> {
  const res = await fetch(
    `${API_URL}/channels/${encodeURIComponent(id)}/voice`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Update channel voice failed: ${res.status} ${text || res.statusText}`,
    );
  }
}

export type StartScriptResponse = {
  task_id: string;
  project_slug: string;
};

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export type TaskSummary = {
  id: string;
  status: TaskStatus;
  exit_code: number | null;
  started_at: number | null;
  finished_at: number | null;
  log_count: number;
  metadata: Record<string, unknown>;
};

export type StageEvent = {
  type: "stage";
  stage: string;
  status: "started" | "completed";
};

export type TaskWithLogs = TaskSummary & {
  logs: string[];
  stage_events?: StageEvent[];
};

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${path} ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return getJSON<ProjectSummary[]>("/projects");
}

export async function getProject(slug: string): Promise<ProjectDetail> {
  return getJSON<ProjectDetail>(`/projects/${encodeURIComponent(slug)}`);
}

export type ProjectCost = {
  total_usd: number;
  by_stage: Record<string, number>;
  by_provider: Record<string, number>;
  entries: Array<Record<string, unknown>>;
};

export async function getProjectCost(slug: string): Promise<ProjectCost> {
  return getJSON<ProjectCost>(`/projects/${encodeURIComponent(slug)}/cost`);
}

export async function createScript(body: ScriptRequest): Promise<StartScriptResponse> {
  return getJSON<StartScriptResponse>("/scripts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function createPipeline(body: ScriptRequest): Promise<StartScriptResponse> {
  return getJSON<StartScriptResponse>("/pipeline", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteProject(slug: string): Promise<void> {
  const res = await fetch(`${API_URL}/projects/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Delete failed: ${res.status} ${res.statusText}`);
  }
}

export async function updateScript(slug: string, script: ScriptDraft): Promise<void> {
  const res = await fetch(
    `${API_URL}/projects/${encodeURIComponent(slug)}/script`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(script),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Update script failed: ${res.status} ${text || res.statusText}`);
  }
}

export type SceneInfo = {
  id: number;
  segment_id: number;
  narration: string;
  visual_description: string;
  /** Effective per-scene visual mode (override → scene tag → segment mode). */
  visual_mode: string | null;
  start_time: number | null;
  end_time: number | null;
  duration: number | null;
  has_footage: boolean;
  footage_url: string | null;
};

export async function getScenes(slug: string): Promise<SceneInfo[]> {
  return getJSON<SceneInfo[]>(`/projects/${encodeURIComponent(slug)}/scenes`);
}

/** Override one scene's visual mode inside a "mixed" segment. Persisted to
 *  visual_config.json scene_overrides; returns the stored effective mode. */
export async function setSceneVisualMode(
  slug: string,
  sceneId: number,
  visualMode: "stock_video" | "ai_image",
): Promise<{ scene_id: number; visual_mode: string }> {
  return getJSON<{ scene_id: number; visual_mode: string }>(
    `/projects/${encodeURIComponent(slug)}/scenes/${sceneId}/visual-mode`,
    { method: "POST", body: JSON.stringify({ visual_mode: visualMode }) },
  );
}

export type StageResponse = { task_id: string; project_slug: string };

export async function startVoiceover(
  slug: string,
  opts?: { voice_speed?: number },
): Promise<StageResponse> {
  return getJSON<StageResponse>("/voiceover", {
    method: "POST",
    body: JSON.stringify({
      project_slug: slug,
      voice_speed: opts?.voice_speed,
    }),
  });
}

export async function startVisuals(slug: string): Promise<StageResponse> {
  return getJSON<StageResponse>("/visuals", {
    method: "POST",
    body: JSON.stringify({ project_slug: slug }),
  });
}

// ---------------------------------------------------------------------------
// Visual provider config (Phase 2 visual generation)
// ---------------------------------------------------------------------------

export type VisualMode = {
  id: string;
  label: string;
};

export type VisualProvider = {
  id: string;
  label: string;
  mode: string;
  available: boolean;
  cost_per_unit?: number;
  unit?: string;
};

export type VisualProvidersResponse = {
  default_mode: string;
  default_provider: string;
  modes: VisualMode[];
  providers: VisualProvider[];
};

export type VisualSegmentConfig = {
  segment_id: number;
  /** Null before scenes are planned (skeleton derived from the script draft);
   *  the real count is filled in once the scene plan exists. */
  scene_count: number | null;
  mode: string;
  /** Dormant for "mixed" segments (routing is per scene). */
  provider: string;
};

/** Per-scene visual-mode override map for "mixed" segments, keyed by scene id
 *  (as a string, matching the JSON object keys). */
export type SceneOverrides = Record<string, "stock_video" | "ai_image">;

/** Wire shape returned by GET /projects/{slug}/visual-config. The backend
 *  wraps the segments under `config` plus a `saved` flag indicating whether
 *  the user has ever written to this project's config explicitly. */
export type VisualConfigResponse = {
  saved: boolean;
  config: { segments: VisualSegmentConfig[]; scene_overrides?: SceneOverrides };
};

export async function getVisualProviders(): Promise<VisualProvidersResponse> {
  return getJSON<VisualProvidersResponse>("/visual-providers");
}

export async function getVisualConfig(
  slug: string,
): Promise<VisualConfigResponse> {
  return getJSON<VisualConfigResponse>(
    `/projects/${encodeURIComponent(slug)}/visual-config`,
  );
}

export async function updateVisualConfig(
  slug: string,
  segments: VisualSegmentConfig[],
  sceneOverrides?: SceneOverrides,
): Promise<void> {
  const res = await fetch(
    `${API_URL}/projects/${encodeURIComponent(slug)}/visual-config`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        sceneOverrides && Object.keys(sceneOverrides).length > 0
          ? { segments, scene_overrides: sceneOverrides }
          : { segments },
      ),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Update visual config failed: ${res.status} ${text || res.statusText}`,
    );
  }
}

export async function startVisualsGenerate(
  slug: string,
): Promise<StageResponse> {
  return getJSON<StageResponse>(
    `/projects/${encodeURIComponent(slug)}/visuals/generate`,
    { method: "POST" },
  );
}

/** Footage-only re-fetch on the existing scene plan: keeps scene_windows /
 *  visual_prompts / visual_config, fills missing/failed/mode-changed scenes.
 *  Does NOT re-plan (no LLM call) — use startVisualsGenerate for a full run. */
export async function startFootageRefetch(
  slug: string,
): Promise<StageResponse> {
  return getJSON<StageResponse>(
    `/projects/${encodeURIComponent(slug)}/visuals/footage/generate`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Visual prompt enhancement (pre-generation step that styles each scene's
// AI-image prompt via the channel preset). Auto-applied, no editing UI.
// ---------------------------------------------------------------------------

export type VisualPromptStatus = {
  exists: boolean;
  scene_count: number;
  generated_at: string | null;
  model: string | null;
  source: "enhanced" | "passthrough" | null;
};

export type VisualPromptModel = {
  id: string;
  label: string;
  cost_per_video_estimate: number;
};

export type VisualPromptModelsResponse = {
  default: string;
  models: VisualPromptModel[];
};

export async function getVisualPromptStatus(
  slug: string,
): Promise<VisualPromptStatus> {
  return getJSON<VisualPromptStatus>(
    `/projects/${encodeURIComponent(slug)}/visual-prompts`,
  );
}

export async function regenerateVisualPrompts(
  slug: string,
): Promise<StageResponse> {
  return getJSON<StageResponse>(
    `/projects/${encodeURIComponent(slug)}/visual-prompts/generate`,
    { method: "POST" },
  );
}

export async function getVisualPromptModels(): Promise<VisualPromptModelsResponse> {
  return getJSON<VisualPromptModelsResponse>("/visual-prompt-models");
}

export type RenderOptions = {
  ken_burns?: boolean;
  render_section_cards?: boolean;
  render_section_transitions?: boolean;
  background_music?: boolean;
  music_volume?: number;
};

export async function startRender(
  slug: string,
  opts?: RenderOptions,
): Promise<StageResponse> {
  return getJSON<StageResponse>("/render", {
    method: "POST",
    body: JSON.stringify({
      project_slug: slug,
      ken_burns: opts?.ken_burns ?? false,
      render_section_cards: opts?.render_section_cards ?? true,
      render_section_transitions: opts?.render_section_transitions ?? true,
      background_music: opts?.background_music ?? false,
      music_volume: opts?.music_volume ?? 0.05,
    }),
  });
}

// ---------------------------------------------------------------------------
// Remotion motion-graphics module (standalone /remotion tab). Renders a garden
// title card to MP4 via the backend task runner; output is served from
// /remotion-out.
// ---------------------------------------------------------------------------

/** Kick off a Remotion MP4 render of the given card composition with the given
 *  props. `comp` must match a card id (see cards/registry.ts). Returns the task
 *  id (for streamTaskLogs) and the output filename (for remotionOutUrl). */
export async function startRemotionRender(
  comp: string,
  props: CardProps,
): Promise<{ task_id: string; filename: string }> {
  return getJSON<{ task_id: string; filename: string }>("/remotion/render", {
    method: "POST",
    body: JSON.stringify({ comp, props }),
  });
}

/** Public URL for a rendered Remotion MP4 (served by the /remotion-out mount). */
export function remotionOutUrl(filename: string): string {
  return `${API_URL}/remotion-out/${filename}`;
}

// ---------------------------------------------------------------------------
// Per-channel graphics design library (Phase 1 persistence). Named designs
// saved from the /remotion designer, keyed by role (title screens, section
// headers, overlays, transitions). `card_id` is a card id (see
// cards/registry.ts); `props` is the full CardProps for that design. snake_case
// leaf keys mirror the backend JSON. `GraphicRole` mirrors ROLES in
// cards/registry.ts and ALLOWED_ROLES in backend/api/routes/remotion.py.
// ---------------------------------------------------------------------------

export type GraphicRole = "title" | "section_header" | "overlay" | "transition";
export type GraphicPreset = { name: string; card_id: string; props: CardProps };
export type GraphicLibrary = { default: string | null; presets: GraphicPreset[] };

/** GET /channels/{id}/graphics/{role} — the channel's saved design library for
 *  one role. */
export async function getGraphics(
  channelId: string,
  role: GraphicRole,
): Promise<GraphicLibrary> {
  return getJSON<GraphicLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/${role}`,
  );
}

/** POST /channels/{id}/graphics/{role} — upsert a named design; returns the
 *  updated library. */
export async function saveGraphic(
  channelId: string,
  role: GraphicRole,
  name: string,
  cardId: string,
  props: CardProps,
): Promise<GraphicLibrary> {
  return getJSON<GraphicLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/${role}`,
    { method: "POST", body: JSON.stringify({ name, card_id: cardId, props }) },
  );
}

/** DELETE /channels/{id}/graphics/{role}/{name} — remove a named design;
 *  returns the updated library. */
export async function deleteGraphic(
  channelId: string,
  role: GraphicRole,
  name: string,
): Promise<GraphicLibrary> {
  return getJSON<GraphicLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/${role}/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// Per-channel transition designs (the /remotion "Transitions" tab). Reuses the
// same {name, card_id, props} record as the card graphics library, filed under
// the "transition" role: `card_id` holds the transition TYPE (see TRANSITION_IDS
// in remotion/transitions/registry.ts) and `props` holds its TransitionParams.
// Design + preview only — NOT wired into the render/assembly pipeline.
// ---------------------------------------------------------------------------

export type TransitionDesign = {
  name: string;
  /** The transition type id (registry.ts), stored in the shared `card_id` slot. */
  card_id: string;
  props: TransitionParams;
};
export type TransitionLibrary = {
  default: string | null;
  presets: TransitionDesign[];
};

/** GET /channels/{id}/graphics/transition — the channel's saved transition
 *  designs. */
export async function getTransitionDesigns(
  channelId: string,
): Promise<TransitionLibrary> {
  return getJSON<TransitionLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/transition`,
  );
}

/** POST /channels/{id}/graphics/transition — upsert a named transition design
 *  ({name, card_id: type, props: params}); returns the updated library. */
export async function saveTransitionDesign(
  channelId: string,
  name: string,
  type: string,
  params: TransitionParams,
): Promise<TransitionLibrary> {
  return getJSON<TransitionLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/transition`,
    {
      method: "POST",
      body: JSON.stringify({ name, card_id: type, props: params }),
    },
  );
}

/** DELETE /channels/{id}/graphics/transition/{name} — remove a named transition
 *  design; returns the updated library. */
export async function deleteTransitionDesign(
  channelId: string,
  name: string,
): Promise<TransitionLibrary> {
  return getJSON<TransitionLibrary>(
    `/channels/${encodeURIComponent(channelId)}/graphics/transition/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}

/** POST /transitions/preview — render the two-clip TransitionPreview stage to a
 *  SHORT MP4. The only way to preview a Tier-B WebGL shader transition (the live
 *  browser <Player> can't run those). Returns the task id (for streamTaskLogs)
 *  and the output filename (for remotionOutUrl), same shape as
 *  startRemotionRender. */
export async function renderTransitionPreview(
  type: string,
  params: TransitionParams,
): Promise<{ task_id: string; filename: string }> {
  return getJSON<{ task_id: string; filename: string }>(
    "/transitions/preview",
    { method: "POST", body: JSON.stringify({ type, params }) },
  );
}

/** Subscribe to a task's SSE log stream. Returns a cleanup function.
 *  ``onStage`` (optional) receives structured stage markers so callers can
 *  render a per-stage checklist without screen-scraping log lines. */
export function streamTaskLogs(
  taskId: string,
  onLog: (line: string) => void,
  onDone: (status: TaskStatus, exitCode: number | null) => void,
  onError?: (err: unknown) => void,
  onStage?: (stage: string, status: "started" | "completed") => void,
): () => void {
  const source = new EventSource(`${API_URL}/tasks/${taskId}/stream`);
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "log") {
        onLog(data.line);
      } else if (data.type === "stage") {
        onStage?.(data.stage, data.status);
      } else if (data.type === "done") {
        onDone(data.status, data.exit_code);
        source.close();
      }
    } catch (err) {
      // Close on parse failure — leaving the EventSource open lets the browser
      // re-deliver the same malformed payload on reconnect, looping forever.
      source.close();
      onError?.(err);
    }
  };
  source.onerror = (err) => {
    onError?.(err);
    source.close();
  };
  return () => source.close();
}

/** Cancel a running task. No-op on the server if already finished. */
export async function cancelTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_URL}/tasks/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Cancel failed: ${res.status} ${text || res.statusText}`);
  }
}

/** POST /channels/{id}/voice-preview — returns an MP3 blob. */
export async function previewChannelVoice(
  id: string,
  text?: string,
): Promise<Blob> {
  const res = await fetch(
    `${API_URL}/channels/${encodeURIComponent(id)}/voice-preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(text ? { text } : {}),
    },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `Voice preview failed: ${res.status} ${detail || res.statusText}`,
    );
  }
  return res.blob();
}

/** Force a single scene's footage to regenerate via its configured provider. */
export async function regenerateScene(
  slug: string,
  sceneId: number,
): Promise<{ scene_id: number; footage_url: string }> {
  return getJSON<{ scene_id: number; footage_url: string }>(
    `/projects/${encodeURIComponent(slug)}/scenes/${sceneId}/regenerate`,
    { method: "POST" },
  );
}

/** List active tasks, optionally filtered. Used by RunPanel to recover an
 *  in-flight run after page reload. */
export async function listTasks(params?: {
  project_slug?: string;
  kind?: string;
  status?: string;
}): Promise<TaskSummary[]> {
  const qs = new URLSearchParams();
  if (params?.project_slug) qs.set("project_slug", params.project_slug);
  if (params?.kind) qs.set("kind", params.kind);
  if (params?.status) qs.set("status", params.status);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJSON<TaskSummary[]>(`/tasks${suffix}`);
}

/** Fetch a task's current state plus its full log buffer. */
export async function getTaskStatus(taskId: string): Promise<TaskWithLogs> {
  return getJSON<TaskWithLogs>(`/tasks/${encodeURIComponent(taskId)}`);
}
