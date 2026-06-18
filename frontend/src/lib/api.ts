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
  conclusion: { narration: string; cta: string };
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
  /** If set, write artifacts to this project slug instead of one derived from topic. */
  project_slug?: string;
  /** Selects the outline/script structure module from video_types.json. */
  video_type?: string;
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

export type StartScriptResponse = {
  task_id: string;
  project_slug: string;
};

export type TaskStatus = "pending" | "running" | "completed" | "failed";

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

export async function createProject(): Promise<{ slug: string }> {
  return getJSON<{ slug: string }>("/projects", { method: "POST" });
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

export async function startRender(slug: string): Promise<StageResponse> {
  return getJSON<StageResponse>("/render", {
    method: "POST",
    body: JSON.stringify({ project_slug: slug }),
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
