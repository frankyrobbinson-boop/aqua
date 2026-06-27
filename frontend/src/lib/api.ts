/** Thin client for the Aqua FastAPI service. */

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
  /** Number of items for the listicle video_type (3–12). Ignored by other types. */
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

export type TaskWithLogs = TaskSummary & { logs: string[] };

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
  narration: string;
  visual_description: string;
  start_time: number | null;
  end_time: number | null;
  duration: number | null;
  has_footage: boolean;
  footage_url: string | null;
};

export async function getScenes(slug: string): Promise<SceneInfo[]> {
  return getJSON<SceneInfo[]>(`/projects/${encodeURIComponent(slug)}/scenes`);
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
  scene_count: number;
  mode: string;
  provider: string;
};

/** Wire shape returned by GET /projects/{slug}/visual-config. The backend
 *  wraps the segments under `config` plus a `saved` flag indicating whether
 *  the user has ever written to this project's config explicitly. */
export type VisualConfigResponse = {
  saved: boolean;
  config: { segments: VisualSegmentConfig[] };
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
): Promise<void> {
  const res = await fetch(
    `${API_URL}/projects/${encodeURIComponent(slug)}/visual-config`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments }),
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
  transition?: "cut" | "fade";
  ken_burns?: boolean;
};

export async function startRender(
  slug: string,
  opts?: RenderOptions,
): Promise<StageResponse> {
  return getJSON<StageResponse>("/render", {
    method: "POST",
    body: JSON.stringify({
      project_slug: slug,
      transition: opts?.transition ?? "cut",
      ken_burns: opts?.ken_burns ?? false,
    }),
  });
}

/** Subscribe to a task's SSE log stream. Returns a cleanup function. */
export function streamTaskLogs(
  taskId: string,
  onLog: (line: string) => void,
  onDone: (status: TaskStatus, exitCode: number | null) => void,
  onError?: (err: unknown) => void,
): () => void {
  const source = new EventSource(`${API_URL}/tasks/${taskId}/stream`);
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "log") {
        onLog(data.line);
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
