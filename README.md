# Aqua

An AI video pipeline that turns a topic into a finished YouTube video. Research → outline → script → voiceover → stock-footage matching → render. FastAPI backend + Next.js frontend. Built for a single creator running it locally; not a hosted product.

## Pipeline

```
Topic
 ├─ Research              (GPT-5 → research.json)
 ├─ Outline               (GPT-5 → outline.json, structured per video type)
 └─ Script draft          (Claude Opus → script_draft.json, JSON-schema enforced)
       │
       ├─ Voiceover       (ElevenLabs TTS → audio chunks + audio_timeline.json)
       ├─ Scene plan      (LLM → scene_plan.json: visual_description per scene)
       ├─ Scene timing    (text-match against audio words → scene_windows.json)
       ├─ Stock footage   (Pexels search + Claude Haiku visual rerank → footage/)
       └─ Render          (ffmpeg: scene clips → concat → subtitles burn → mux)
                                                    ↓
                                              final.mp4
```

Each stage is cached so reruns are cheap. Editing the script invalidates only what depends on it.

## Prerequisites

- **Python 3.14** (or 3.12+; tested on 3.14)
- **Node.js 20+** and **npm**
- **ffmpeg 8.x** — earlier versions may work but the `alimiter` audio filter has different units in <8.0 (see `services/assembly_service.py` for the linear-amplitude value used)
- API keys: OpenAI, Anthropic, ElevenLabs, Pexels (all have free tiers sufficient for testing)

## Setup

```bash
git clone https://github.com/<your-username>/aqua.git
cd aqua

# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and paste in your API keys.
cd ..

# Frontend
cd frontend
npm install
cd ..
```

## Running

Open two terminals.

**Terminal 1 — backend (FastAPI on :8000):**
```bash
cd backend
source venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — frontend (Next.js on :3000):**
```bash
cd frontend
npm run dev
```

Visit http://localhost:3000.

### CLI-only alternative

Every UI button is backed by a `run_*.py` script you can invoke directly from `backend/`:

```bash
venv/bin/python run_script_only.py "Your topic here" 10        # research + outline + script
venv/bin/python run_audio.py <project-slug>                    # voiceover
venv/bin/python run_visuals.py <project-slug>                  # scene plan + scene timing + footage fetch
venv/bin/python run_render.py <project-slug>                   # final video
venv/bin/python run_full_pipeline.py "Topic" 10                # end-to-end
```

Generated videos land in `projects/<slug>/video/final.mp4`.

## Repo layout

```
backend/
  api/               FastAPI routes (script/voiceover/visuals/render endpoints, task runner)
  prompts/           LLM prompts split by stage + channel + video type + hook archetype
  services/          Per-stage business logic (research, outline, script, voice, visuals, assembly)
  run_*.py           CLI entry points for each stage
frontend/
  src/app/           Next.js App Router pages (/, /create, /projects, /channels)
  src/components/    React components
  src/lib/api.ts     Thin HTTP client for the FastAPI backend
projects/            Generated video output. Gitignored (videos are large).
CLAUDE.md            Manager/implementer dev protocol used with Claude Code (see below)
ROADMAP.md           Current priorities and planned work
```

## Prompt architecture

Three-layer composition:
- **Universal base** — `script_base.md`, `outline_base.md`, `research.md`. Apply to every video.
- **Channel** — `channels/<id>.md` defines narrator personality, audience, voice rules. One channel preset today (`gardening`). Spliced into base via `{{CHANNEL}}` slot.
- **Per video** — `script_modules/<type>.md` for structural rules (listicle, deep_dive, story, myth_bust). `hook_archetypes/<id>.md` for Beat-1 opening style (scene, contrast, counter-claim, specific-result, bold-claim). Both spliced via slots.

The registries (`channel_registry`, `video_type_registry`, `hook_archetype_registry`) verify at boot that every slot exists in the base files and every module file exists on disk.

## Channels

The first channel preset is `gardening`. To add a new channel:

1. Create `backend/prompts/channels/<id>.md` with `## Narrator`, `## Audience`, `## Voice rules` sections.
2. Add an entry to `backend/prompts/channels.json` (`id`, `name`, `description`, `channel_module`, `preferred_hook_archetype`).
3. Restart the backend — the boot guard validates the new entry.

## Dev protocol

`CLAUDE.md` documents a manager/implementer protocol used when working with [Claude Code](https://claude.com/claude-code). It's optional — if you use a different editor or AI assistant, ignore it. The codebase doesn't depend on the protocol; it's purely a workflow agreement.

## Roadmap

See `ROADMAP.md` for current priorities. Short version: script-quality iteration → channel UI polish → AI image/video providers → manual editing stage.

## License

This project does not currently include a LICENSE file. All rights reserved by default. If you intend to fork or build on it, open an issue first.
