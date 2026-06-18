# Aqua Roadmap

Snapshot: 2026-06-17. Personal-use stage, not yet a real product. The lever right now is **content quality, not feature breadth** — prompt work outranks UI work until the user explicitly raises a UI pain.

For deeper rationale on any item, look in `~/.claude/projects/-Users-aidanmcomie-Documents-Aqua/memory/` (referenced inline as `[[memory-name]]`).

---

## Current state at a glance

| Track | Status |
|---|---|
| Backend reliability + parallelization | ✅ DONE |
| Stage-graph architecture | ✅ DONE |
| Script-stage Phase 1 (loose ends, structured research) | ✅ DONE |
| Script-stage Phase 2 (3-beat hook structure) | ✅ DONE |
| Script-stage Phase 3 (channel-aware refactor) | ✅ DONE |
| Frontend per-video flow cleanup (shared form) | ✅ DONE |
| Script-stage Phase 4 (channel through research + outline) | 📋 PLANNED |
| Script-stage Phase 5 (per-video hook archetype override) | 📋 PLANNED |
| Script-stage Phase 6 (Channel UI) | 📋 PLANNED |
| Script-stage Phase 7 (channel sample pool) | 📋 PLANNED |
| Content-quality short-term batch | 📋 PLANNED |
| Per-video polish (manual override, scene editor, etc.) | 📋 PLANNED |
| Stock footage provider swap | 📋 PLANNED |
| AI image/video providers + per-segment policy | 📋 PLANNED |
| Video editing stage | 📋 PLANNED (long) |
| EDL-driven assembly | 📋 PLANNED (long) |
| Video editing learning loop | 📋 PLANNED (long) |

---

## Backend reliability + architecture — ✅ DONE

Three batches of code-review fixes shipped, plus the stage-graph refactor.

**Batch 1** — top-5 from `/code-review`:
- Parallel visuals fetching (8 workers, `services/visual_service.py`)
- Per-clip render cache via sidecar JSON (`services/assembly_service.py`)
- `update_script` payload validation via Pydantic (`api/routes/projects.py`)
- `voice_speed` plumbing end-to-end (form → config → subprocess → ElevenLabs native)
- `asyncio.Task` strong-ref to prevent GC mid-run (`api/routes/tasks.py`)

**Batch 2** — next 5:
- `PROJECTS_ROOT` file-anchored (no more CWD breakage)
- `_patch_script_config` per-slug asyncio lock + atomic writes
- EventSource closed on JSON parse failure (no replay storm)
- Footage cache sidecar keyed by `visual_description` (catches stale clips on query edit)
- `_REGISTRY` LRU + `DELETE /tasks/{id}` cancel endpoint + stale-audio mtime check

**Batch 3** — final 3:
- `stream_logs` double-check pattern (multi-consumer race fix)
- Parallel ElevenLabs across segments (`ELEVENLABS_CONCURRENCY=3` default, ~3x speedup)
- `_project_summary` mtime fix (4-path stat instead of `rglob` avalanche)

**Stage-graph architecture** — `services/stage_graph.py`:
- Single source of truth for stage inputs/outputs/caches
- `is_stage_fresh(project_dir, name)` — outputs exist + newer than inputs
- `invalidate_dependents(project_dir, artifact)` — transitive walk, preserves caches
- Cascade-invalidate (script edit) now derives from the graph, not hand-maintained lists
- Caches (audio/, footage/, clips/) preserved on cascade — sidecars handle staleness

**Constraint honored:** native TTS settings for in-clip prosody, ffmpeg only between clips (`assemble_audio` chain). See [[feedback-voice-native-settings]].

---

## Script stage phases

The script stage is the most-architecturally-complete part of the codebase. Three of seven planned phases are done.

### Phase 1 — Loose-ends cleanup — ✅ DONE
- Deleted `.bak` files (`prompts/outline.md.bak`, `prompts/script_draft.md.bak`)
- Wired `prompts/research.md` into `services/research_service.py` (was dead code; now `instructions=` to gpt-5, output parsed as JSON)
- Downstream `outline_service.py` + `script_draft_service.py` render structured research via `json.dumps`

### Phase 2 — 3-beat hook structure — ✅ DONE
- `script_base.md` Hook section replaced with 3-beat structure (catch / re-hook / transition) with word budgets per beat
- Dropped "No reference dumps" rule from both base files and `script_modules/listicle.md` per user instruction
- Meta-rule added: "Voice rules govern how you speak; structure rules govern how you organize. Voice wins on conflict."

### Phase 3 — Channel-aware refactor — ✅ DONE
- `prompts/channels.json` — registry mirroring `video_types.json`
- `prompts/channels/gardening.md` — first channel (narrator, audience, voice rules extracted from base files)
- `services/channel_registry.py` — mirror of `video_type_registry.py`
- Base prompts (`script_base.md`, `outline_base.md`) now channel-agnostic; gardening voice no longer hardcoded
- `compose_*_prompt` accepts `channel_content` arg, splices `{{CHANNEL}}` slot
- `verify_base_slots()` enforces `{{CHANNEL}}` exists
- `script_config.json` carries `channel` field; defaults to `gardening` via registry
- `GET /channels` endpoint ready for UI
- `[[feedback-script-voice]]` reframed as gardening-channel-specific, not Aqua-wide

See [[project-script-prompt-architecture]] for the three-layer model (global / channel / video).

### Phase 4 — Channel context through research + outline — 📋 PLANNED
- Thread channel's `audience` prose into the research prompt as framing context for `interesting_angles` (NOT as a filter on facts)
- Outline already gets channel via `{{CHANNEL}}` slot; minor — confirm voice rules shape section purposes correctly
- Small batch, slots in cleanly after Phase 3

### Phase 5 — Per-video hook archetype override — 📋 PLANNED
- Add optional `hook_archetype` to `script_config.json` (None = use channel's preferred Beat-1 archetype)
- One dropdown on the per-video form sourced from a global archetype menu (scene / contrast / counter-claim / specific-result / bold-claim)
- Beat 1 prompt copy updates to read the override

### Phase 6 — Channel UI — 📋 PLANNED (test gate)
- `/channels` list page reading `GET /channels`
- `/channels/[id]` edit page — narrator, audience, voice rules, preferred Beat-1 archetype, ElevenLabs voice ID, default voice speed, visual policy
- Wire the existing disabled Channel dropdown on `/create`'s ScriptCreationForm to `GET /channels`
- Send `channel` in POST bodies
- **This is the gate** for end-to-end testing the Phase 3 channel backend, per the user's "I would like to test it once the structure of the UI and pipeline is better"

See [[project-channel-presets]] for the full channel field set.

### Phase 7 — Channel sample pool — 📋 PLANNED
- Per-channel user-curated pool of vetted reference scripts
- Splices into `{{CHANNEL_SAMPLE_POOL}}` slot in script_base.md
- **NOTE:** This is user-curated only. The learning-from-edits loop ([[project-video-editing-stage]]) is for the **video editing stage**, NOT for script editing. See [[project-sample-script-inputs]].

---

## Frontend per-video flow cleanup — ✅ DONE

- `components/ScriptCreationForm.tsx` — shared form for both `/create` (Step 1) and `/projects/[slug]` (no-script state)
- Voice speed consolidated to Voiceover tab only (removed from both script forms)
- Channel dropdown placeholder in the shared form, ready to wire for Phase 6
- Both entry points still exist (`/create` + `/projects` → "New project") but now backed by one component
- Orphan imports cleaned, dead components removed

**Open structural decision:** single canonical entry point. Currently both `/create` and "New project" land at the same flow via the shared component. Per [[project-create-page-repurpose]], `/create` will eventually repurpose as the channel-preset builder; "New project" stays the per-video entry. Defer until channels exist.

---

## Content quality — short-term track — 📋 PLANNED

Per [[project-content-quality-priorities]], this is the priority. Each item is pure prompt work (no infra, no API costs to add).

1. **Exercise Phase 1+2 against real outputs.** Run the pipeline a few times, see what the 3-beat hook + structured research actually produces. Iterate prompts based on results.
2. **Title-as-recurring-frame.** Thread the title's central claim through every segment as a recurring thread — don't state once and abandon.
3. **Voice-tone preset registry.** Mirror the video_type registry: three starter presets (conversational, silly, authority) as `prompts/voice_tones/*.md` modules. Channel-level eventually, video-level now.
4. **LLM rerank tier-up.** Haiku → Sonnet for low-confidence visual matches. Catches the "pregnant woman eating orange for a gardening clip" kind of misfire.
5. **Subtitle ~100ms offset.** Trivial: `SUBTITLE_OFFSET = -0.10` constant in `services/subtitle_service.py`.

**Constraint:** per [[feedback-script-voice]], defer to user judgment on examples. Propose structural rules; don't write finished hooks or worked examples into the prompt body.

---

## Per-video polish — 📋 PLANNED

Quality-of-life on the project workspace. Independent of channels; can be done in parallel.

6. **Per-scene manual footage override UI.** On the Visuals tab scene grid — "replace" action that accepts a URL or file upload. Saves to `footage/scene_NNN.mp4` and marks the scene locked.
7. **Per-scene approve/needs-review flag.** Gates the render button on every scene being approved. Forces a quick visual pass before paying for the libass render.
8. **Inline scene editor.** Edit `visual_description` per scene → refetch just that scene (using the existing per-clip sidecar cache to invalidate cleanly).
9. **Per-segment scene density tuning.** Hook denser than body — prompt change in `prompts/scene_plan.md`. Foundation already in place (segments carry `segment_id`/`segment_title`).
10. **Title cards at segment boundaries.** Overlay the segment title (white on translucent fill) over the first ~2s of its first scene. ffmpeg `drawtext`.
11. **Crossfades between scenes.** Switch from concat demuxer to `filter_complex` with `xfade`. Slower render, much better feel.

---

## Stock footage provider swap — 📋 PLANNED

Pexels has indexing issues even with the Haiku rerank. Bigger library needed. See [[project-stock-footage-plan]].

- **Step 1:** archive current Pexels code (copy, don't delete)
- **Step 2:** research providers — Storyblocks, Artgrid, Adobe Stock, others. Cheapest with widest selection wins.
- **Step 3:** implement as another `StockProvider` (the abstraction is in place)
- Per-clip cache sidecar logic (Fix #8) carries over unchanged

---

## AI image/video providers — 📋 PLANNED

The autotube.pro reference + the user's "AI throughout / scattered / hook-heavy" priority. See [[project-visuals-future]].

- **Per-segment `visual_mode`** — `stock | ai_image | ai_video | mixed`. Default policy lives on the channel preset.
- **Per-segment `provider`** — `pexels | grok_imagine | veo_31 | …`. Channel defaults, per-video overrides.
- **Placement policies** — `all_ai` / `hook_heavy` / `scattered` / `none` as named presets.
- **Click-to-split timeline editor for visuals planning** — far-future UX sugar. Hovering surfaces transcript at the timestamp. Manual override on top of AI's default segmentation.
- Foundation already in place: `StockProvider` abstraction, `scene_plan` carries `segment_id`, per-clip sidecar cache. Adding new providers shouldn't require ripping anything up.

---

## Video editing stage — 📋 PLANNED (long-term)

New pipeline stage between visuals and render. See [[project-video-editing-stage]].

- **Effects:** transitions (cut / fade / xfade), big on-screen text overlays, sound effects, fades, music ducks, B-roll layering
- **EDL format** — Edit Decision List as the structured JSON output of the editing stage and input to render. One file, three consumers (manual editor, AI predictor, ffmpeg renderer).
- **Manual UI first** — drag-to-place effects, preview. Out of scope until per-video tabs are solid (Phase 6 + per-video polish).
- **Channel-level editing signature** — snappy/cinematic/etc. Default style + signature effects per channel.

---

## EDL-driven assembly — 📋 PLANNED (long-term, gated on editing stage)

Once the EDL format exists:
- Render stage becomes EDL-consumer instead of hard-coded ffmpeg
- A/B test edit treatments on the same script + audio without regenerating either
- Foundation for the editing learning loop

---

## Video editing learning loop — 📋 PLANNED (long-term, weeks)

The user's "manual editing first, AI learns from it" plan. See [[project-video-editing-stage]].

1. Build manual editing tools in the Render tab (transitions, overlays, music, etc.)
2. Emit an EDL file after every manual edit
3. Edit 10–20 videos by hand to accumulate (script, scene_plan, audio_timeline, EDL) tuples per channel
4. Train: give the model the script + scene plan + a few EDL examples for that channel, ask it to predict the next video's EDL. Few-shot first; fine-tune later if needed.

**Per-channel learning** — never average EDLs across channels. The pool is the channel's editing voice.

---

## `/create` page repurpose — 📋 PLANNED (gated on Channel UI)

Per [[project-create-page-repurpose]]:
- `/create` (or `/channels/new`) becomes the channel-preset builder
- "New project" on `/projects` stays the canonical per-video entry
- Disabled placeholders on `/create` (Provider, Model, Voice ID, AI fallback, Resolution, Subtitles toggle, etc.) light up as channel-level configuration

**Do NOT remove the disabled placeholders** — they're roadmap markers, per [[feedback-keep-placeholders]].

---

## Constraints to honor (durable, do not violate)

- **In-clip vs between-clip audio.** Native TTS settings (`ElevenLabs.VoiceSettings.speed`) for in-clip prosody; ffmpeg only between clips (loudnorm, alimiter, dynaudnorm, trailing-trim, gap silence). [[feedback-voice-native-settings]].
- **Defer to user judgment on script examples.** Propose rules and structure; don't write finished example hooks. [[feedback-script-voice]].
- **Keep disabled placeholder UI.** TopNav `/channels` and `/tools` links, disabled `/create` placeholder controls — all roadmap markers, leave alone. [[feedback-keep-placeholders]].
- **Content quality > feature breadth** until the user explicitly signals otherwise. Prompt work outranks UI work. [[project-content-quality-priorities]].
- **Per-channel learning, never global.** Sample pools and (future) edit-learning corpora are channel-scoped. Averaging across channels mushes voices. [[project-channel-presets]].

---

## Decision gates

- **Short-term content → Medium-term polish:** are the hooks visibly better after a few runs? If no, more prompt iteration before features.
- **Medium-term → Channel UI (Phase 6):** does the per-video flow feel solid enough that you're not constantly hitting friction? If no, more polish first.
- **Channel UI → AI providers:** does the channel system work end-to-end through real video runs? If no, fix that before adding providers.
- **Per-video flows → Video editing stage:** have you edited several videos manually and noticed common patterns worth automating? If no, the learning corpus doesn't exist yet.

---

## What's NOT on the roadmap (intentionally deferred)

- **Removing disabled placeholders.** All planned channel-preset slots — leave alone.
- **Removing TopNav `/channels` and `/tools` links.** Roadmap markers.
- **Single-canonical-entry-point question.** Both `/create` and "New project" coexist now, backed by one shared component. Resolution comes when `/create` repurposes (post Phase 6).
- **Dead legacy entry points** (`backend/pipeline.py`, `backend/main.py`, `backend/test-research.py`). Pre-frontend scripts; harmless. Delete during any cleanup pass if it comes up.
- **Channel-neutralizing the structure modules** further. Light gardening flavor remains in `script_modules/listicle.md` ("feeds the plant" example). Not load-bearing; fix when adding a second channel.

---

## Memory file index (for a fresh session)

All in `~/.claude/projects/-Users-aidanmcomie-Documents-Aqua/memory/`:

- `project_content_quality_priorities.md` — hook > on-topic voice > footage > AI placement; prompt work outranks UI
- `project_channel_presets.md` — channels bundle narrator + audience + voice rules + visual policy + sample pool + editing signature
- `project_script_prompt_architecture.md` — three-layer split: global / channel / video
- `project_create_page_repurpose.md` — `/create` → channel-preset builder eventually
- `project_visuals_future.md` — per-segment provider/mode/policy + AI providers reference
- `project_stock_footage_plan.md` — Pexels swap plan (archive first)
- `project_video_editing_stage.md` — transitions/text/SFX/fades stage + learning loop
- `project_sample_script_inputs.md` — user-provided script references (NOT post-edit learning)
- `project_post_v1_backlog.md` — extensive backlog: audio polish, footage rerank, editing polish, prompt editor, scene editor, EDL, channels
- `feedback_script_voice.md` — gardening-channel voice rules (channel-scoped, not Aqua-wide)
- `feedback_voice_native_settings.md` — in-clip vs between-clip rule
- `feedback_keep_placeholders.md` — don't propose removing inert roadmap UI

---

**Bottom line for a fresh session:** Phases 1–3 of the script stage are done, frontend duplication is cleaned up, channel system is wired backend-only. Next priority is content quality (short-term track), then Channel UI (Phase 6, the test gate), then per-video polish. AI providers and the video editing stage are the big long-term lifts, gated on channels being solid.
