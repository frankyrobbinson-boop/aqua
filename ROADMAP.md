# Aqua Roadmap

Snapshot: 2026-06-18. Personal-use stage, not yet a real product. The lever right now is **content quality, not feature breadth** — prompt work outranks UI work until the user explicitly raises a UI pain.

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
| Script-stage Phase 4 (channel through research + outline) | ✅ DONE |
| Script-stage Phase 5 (per-video hook archetype override) | ✅ DONE |
| Script-stage Phase 6 (Channel UI test gate, read-only) | ✅ DONE |
| Script-quality round 1 (orientation + listicle beats) | ✅ DONE |
| Drift bug fixes (audio trim, alimiter, scene timing, gap mp3) | ✅ DONE |
| Pipeline UX fixes (naming, status reload, dedup footage) | ✅ DONE |
| Collaboration: public GitHub repo | ✅ DONE |
| Script-stage Phase 7 (channel sample pool) | 📋 PLANNED |
| Script-quality round 2 (research-stage feedstock) | 📋 PLANNED |
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

The script stage is the most-architecturally-complete part of the codebase. Six of seven planned phases are done.

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

### Phase 4 — Channel context through research + outline — ✅ DONE
- New `resolve_channel_section(channel_id, section)` in `channel_registry.py` extracts markdown sections from channel modules
- `prompts/research.md` gets a `{{AUDIENCE_BLOCK}}` slot between content goals and JSON schema; research_service splices in the channel's `## Audience` prose, framed as guidance for `interesting_angles` only (accuracy rules remain dominant)
- `run_script_only.py` threads `channel` to `generate_research`
- `outline_base.md` `purpose` field expanded with "for this channel's audience" framing
- New `verify_research_slot()` boot guard wired into `api/main.py`

### Phase 5 — Per-video hook archetype override — ✅ DONE
- New `prompts/hook_archetypes.json` registry + 5 markdown modules (scene / contrast / counter-claim / specific-result / bold-claim)
- `services/hook_archetype_registry.py` mirrors video_type pattern with `resolve_archetype(per_video, channel)` fallback chain
- `channels.json` gets `preferred_hook_archetype` field (gardening → "scene")
- `script_base.md` Beat 1 now reads `{{HOOK_ARCHETYPE_BLOCK}}` — channel-specific parenthetical removed
- `script_draft_service.generate_script_draft` takes `hook_archetype` param; `compose_script_prompt` splices the resolved block
- API: `ScriptRequest.hook_archetype` field, validated against registry, written to `script_config.json`; `GET /hook-archetypes` endpoint
- Frontend: `HookArchetypeSelect` component with "Channel default" sentinel, wired into `ScriptCreationForm`
- Boot guards: `verify_archetype_modules_exist` + `verify_hook_slot`

### Phase 6 — Channel UI (test gate) — ✅ DONE
- `GET /channels/{id}` endpoint returns id/name/description + `preferred_hook_archetype` + label + sections dict
- New `list_channel_sections(channel_id)` parses ALL `## ` headings dynamically (future channels with new sections auto-surface)
- `/channels` list page + `/channels/[id]` detail page with section cards
- `ChannelSelect` component replaces the disabled placeholder dropdown on `ScriptCreationForm`
- `channel` now sent in POST bodies; end-to-end channel selection works
- **Read-only for now.** Edit-in-UI is out of scope — edit the .md files directly.

### Phase 7 — Channel sample pool — 📋 PLANNED
- Per-channel user-curated pool of vetted reference scripts
- Splices into `{{CHANNEL_SAMPLE_POOL}}` slot in script_base.md
- **NOTE:** This is user-curated only. The learning-from-edits loop ([[project-video-editing-stage]]) is for the **video editing stage**, NOT for script editing. See [[project-sample-script-inputs]].

---

## Script quality

### Round 1 — orientation + listicle beats — ✅ DONE

After four passes of analysis (mine + three Opus iterations) on the cucumber-fertilizer test script vs. two successful reference scripts, landed a coordinated edit across base + listicle + channel-voice files.

**`script_base.md`** — new `# Orientation` block (universal):
- Promise targets a pain (not optimization)
- External villain (industry / conventional wisdom / "free = worthless" assumption) — never the viewer
- Identity-conferring close ("the kind of gardener who…") — never a recap
- Conviction with magnitude guard (reframe changes emphasis, never magnitude or certainty)
- "Tension thread must carry" — antagonist resurfaces in ≥2 mid-body transitions and pays off near the end
- Beat 3 of hook strengthened to "antagonist + transition" (~25–35 words)
- Conclusion rewritten: identity beat + callback to opening AND villain (never a recap)

**`outline_base.md`** — thesis rule (one-sentence claim stronger than "here are N things"), hook field becomes a structured string (Stakes / Villain / Withheld promise / Transition thread), purpose field expanded with curiosity-gap + optional authority anchor + mistake-as-led-into framing.

**`script_modules/listicle.md`** — full restructure:
- Hook anti-enumeration rule (may promise count + stakes, must NOT name items)
- 6-8 beats per item-section: question → reveal → mechanism → optional authority → optional analogy → mistake-as-cliffhanger → loop out
- Authority + analogy beats are **opportunistic, no quota** (skip if research lacks one — never invent or stretch)

**`channels/gardening.md`** — narrator now "calmly certain" (composes with universal conviction without being performative). Tension-thread bullet replaced with "carry the villain installed in the hook" — externalized antagonist framing.

See [[project-script-quality-principles]] (to be written) for the underlying principles synthesized from the Opus analyses.

### Round 2 — research-stage feedstock — 📋 PLANNED

Opus 4's deepest insight: the scriptwriter can't dramatize material that doesn't exist upstream. The accuracy rules correctly forbid invention; the research prompt currently asks for facts and statistics, so it returns stat-shaped material — the script can't produce Liebig-style anecdotes because none exist in the JSON.

Round 2 additions to `prompts/research.md`:
- `origin_stories` field — who / year / institution / what_changed / confidence / source. Returns `null` when unknown. Makes named-authority anchors possible.
- `mechanisms` field — per-item mechanism + analogy/metaphor (optional — skip rather than force).
- Promote `common_mistakes` to first-class field (currently improvised by scriptwriter — fabrication risk).
- `sensory_markers` field — color, smell, texture (feeds visual_notes + sensory-reveal beats).
- Tagged "forgotten knowledge" guidance for `interesting_angles` — defensible version only ("no patent on a banana peel"), never conspiracy ("industry suppressed for 70 years").

**Decision gate:** exercise Round 1 against real videos first. If hooks + segments are visibly better, decide Round 2 priority based on what's still thin.

---

## Frontend per-video flow cleanup — ✅ DONE

- `components/ScriptCreationForm.tsx` — shared form for both `/create` (Step 1) and `/projects/[slug]` (no-script state)
- Voice speed consolidated to Voiceover tab only (removed from both script forms)
- Channel dropdown live (Phase 6); Hook opening dropdown live (Phase 5)
- Both entry points still exist (`/create` + `/projects` → "New project") backed by one component
- Orphan imports cleaned, dead components removed

**Open structural decision:** single canonical entry point. Per [[project-create-page-repurpose]], `/create` will eventually repurpose as the channel-preset builder; "New project" stays the per-video entry. Defer until you've actually felt the friction.

---

## Drift bug fixes — ✅ DONE

Four bugs in one family — same pattern: time computed-and-quantized in one place vs. measured-from-real-artifacts in another, accumulating across long videos.

1. **Audio timeline trim** — `voice_service` advanced cursor by un-trimmed `speech_duration` while `assembly_service` trimmed 30 ms off each chunk's outpoint. Fix: trim upstream in `voice_service` so timeline reflects the assembled audio.
2. **ffmpeg alimiter unit change** — `alimiter` `limit` param flipped from dB to linear amplitude in ffmpeg 8.x. `limit=-1.0` rejected with "Result too large." Fix: `0.891251` (linear equivalent of −1.0 dBFS).
3. **Scene timing proportional mapping** — `compute_scene_windows` distributed scenes proportionally to word counts, which doesn't match actual speaking time. Up to 8.4 s drift between visuals and narration in a 10-min video. Fix: exact text matching — find each scene's first words in the audio_timeline word list, use the matched word's `global_start`. Sample-accurate with shorter-needle fallback and proportional-for-one-scene fallback that doesn't pollute downstream.
4. **gap.mp3 frame quantization + format mismatch** — MP3 frames are 1152 samples; a "0.3 s" gap.mp3 actually encoded to 0.340 s (~40 ms drift per gap, ~0.9 s across a 24-chunk video). First attempted fix swapped to gap.wav, which broke harder: concat demuxer's shared decoder rejected the WAV with "Invalid data found," dropping ALL gaps (7.2 s missing audio). Final fix: rewrite `assemble_audio` to use ffmpeg concat *filter* with inline `anullsrc` source — each chunk decodes independently, gaps are sample-accurate PCM, `aresample` + `aformat` normalize chunk streams before concat.

**Audit findings — bounded, may need revisit later:**
- M1: `-shortest` mux flag could chop final video if scene clip frame-snap (25fps = 40 ms quantization) diverges from audio length. Bounded today; worth re-measuring after several renders.
- M3: `-c copy` concat across re-encoded scene clips might add small PTS nudges. Feeds M1.
- Script-stage RunPanel hydration gap — Fix 2 covers voiceover/visuals/render but `ScriptCreationForm` doesn't auto-restore in-flight script-stage logs after a slug migration (covered in scope notes).

**Pattern lesson** (now a constraint — see Constraints section): when timing matters, use measured/exact, never proportional or quantized. Future stages (editing, EDL, AI providers) should inherit this discipline. See [[project-drift-bug-pattern]] (to be written).

---

## Pipeline UX fixes — ✅ DONE

1. **Project naming from title** — submitting the script form with a `draft-…` slug now renames the folder to `slugify(topic)` (with `-2`, `-3` suffix on collision). Frontend `router.replace` to the new URL.
2. **Status box persists on reload** — `GET /tasks` accepts `project_slug` + `kind` + `status` filters. `RunPanel` hydrates from in-flight tasks on mount with an `attached`-flag race guard (manual start always beats late hydration).
3. **Dedupe stock footage across scenes** — `visual_service` maintains a `used_clip_ids` set across the run, pre-populated from cached scenes' sidecars. When the reranker's pick is already used, swap to the next unused candidate from the same rerank pool (lock-guarded; downloads stay parallel).

---

## Collaboration — ✅ DONE

- Public GitHub repo: **`github.com/frankyrobbinson-boop/aqua`**
- README rewritten with prereqs, setup, run modes (CLI + UI), repo layout, prompt architecture
- `backend/.env.example` template (5 keys: OpenAI, Anthropic, ElevenLabs API + voice ID, Pexels)
- `requirements.txt` refreshed via `pip freeze`

**Optional follow-ups when convenient:**
- Branch protection on `main` (no force push, require PR) — Settings → Branches in the GitHub UI
- Add a LICENSE (without one it's "all rights reserved" — fine for now; blocks formal reuse outside the repo)
- Fix git committer identity (`aidanmcomie@Aidans-Laptop.local` from hostname — set with `git config --global user.email`)

---

## Content quality — short-term track — 📋 PLANNED

Per [[project-content-quality-priorities]], this remains the priority over feature breadth. Round 1 prompts landed (see above). Outstanding items:

1. **Exercise Round 1 against real videos.** Run a few. Are hooks visibly better? Does the externalized villain carry? Does the listicle's hook-anti-enumeration + 6-8 beat structure produce richer segments? Iterate prompts based on results.
2. **Title-as-recurring-frame, outline-level only.** Add an outline-stage rule: "Each section's `purpose` must be defensible as a partial answer to the title. If a section can't, replace or cut." Forcing the title-thread at planning time produces less awkward repetition than forcing it at writing time. Skip the riskier script-stage variants (Beat 3 explicit naming, etc.) until needed.
3. **LLM rerank tier-up.** Haiku → Sonnet for low-confidence visual matches. Catches the "pregnant woman eating orange for a gardening clip" kind of misfire.

**Removed from this list** (with reasons, so they don't quietly reappear):
- ~~Voice-tone preset registry~~ — channel voice already covers it; adding generic presets on top would muddy who owns "how this video sounds."
- ~~Subtitle ~100 ms offset constant~~ — the perceived caption drift was actually four upstream timing bugs (now fixed). Re-measure after a fresh render; if the offset is still needed it'll be small and uniform.

**Constraint:** per [[feedback-script-voice]], defer to user judgment on examples. Propose structural rules; don't write finished hooks or worked examples into the prompt body.

---

## Per-video polish — 📋 PLANNED

Quality-of-life on the project workspace. Independent of channels; can be done in parallel.

6. **Per-scene manual footage override UI.** On the Visuals tab scene grid — "replace" action that accepts a URL or file upload. Saves to `footage/scene_NNN.mp4` and marks the scene locked.
7. **Scene-level selector (shape TBD).** Originally "approve/needs-review" — dropped (gates render on every scene being touched, friction with no clear payoff). What replaces it depends on actual pain — maybe a multi-select for batch operations (refetch, swap provider) or a status pill (locked/auto/failed). Defer until real usage exposes the need.
8. **Inline scene editor.** Edit `visual_description` per scene → refetch just that scene (using the existing per-clip sidecar cache to invalidate cleanly).
9. **Per-segment scene density tuning.** Hook denser than body — prompt change in `prompts/scene_plan.md`. Foundation already in place (segments carry `segment_id`/`segment_title`).
10. **Title cards at segment boundaries.** Overlay the segment title (white on translucent fill) over the first ~2s of its first scene. ffmpeg `drawtext`.
11. **Crossfades between scenes.** Switch from concat demuxer to `filter_complex` with `xfade`. Slower render, much better feel.

---

## Stock footage provider swap — 📋 PLANNED

Pexels has indexing issues even with the Haiku rerank. Bigger library needed. See [[project-stock-footage-plan]].

- **Step 1:** archive current Pexels code (copy, don't delete)
- **Step 2:** research providers — Storyblocks (subscription, widest selection, partner API gated), Pond5 (per-asset + subscription, public API), Adobe Stock (per-asset + subscription, public API), Shutterstock (per-asset + subscription, public API), Pixabay (free + API, similar limitations to Pexels). **TODO: get current pricing + API access status for each before committing.**
- **Step 3:** implement as another `StockProvider` (the abstraction is in place)
- Per-clip cache sidecar logic + cross-scene dedup carry over unchanged

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
- **Preset-based UI (per user direction):** click on the timeline at a point → menu of preset insertables (big text card, label, arrow, fade, transition). Start with 4–5 presets; add more as needed. Each preset is structured data (text content, duration, position) so the EDL output is consumable by both manual UI and a future AI predictor.
- **EDL format** — Edit Decision List as the structured JSON output of the editing stage and input to render. One file, three consumers (manual editor, AI predictor, ffmpeg renderer).
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

1. Build manual editing tools in the Render tab (preset insertion per above)
2. Emit an EDL file after every manual edit
3. Edit 10–20 videos by hand to accumulate (script, scene_plan, audio_timeline, EDL) tuples per channel
4. Train: give the model the script + scene plan + a few EDL examples for that channel, ask it to predict the next video's EDL. Few-shot first; fine-tune later if needed.

**Per-channel learning** — never average EDLs across channels. The pool is the channel's editing voice.

---

## `/create` page repurpose — 📋 PLANNED (gated on Channel UI maturity)

Per [[project-create-page-repurpose]]:
- `/create` (or `/channels/new`) becomes the channel-preset builder
- "New project" on `/projects` stays the canonical per-video entry
- Disabled placeholders on `/create` (Provider, Model, Voice ID, AI fallback, Resolution, Subtitles toggle, etc.) light up as channel-level configuration

**Do NOT remove the disabled placeholders** — they're roadmap markers, per [[feedback-keep-placeholders]].

Phase 6 shipped read-only channel viewing; this repurpose comes after enough channel-editing capability exists to justify a dedicated builder route.

---

## Constraints to honor (durable, do not violate)

- **In-clip vs between-clip audio.** Native TTS settings (`ElevenLabs.VoiceSettings.speed`) for in-clip prosody; ffmpeg only between clips (loudnorm, alimiter, dynaudnorm, trailing-trim, gap silence). [[feedback-voice-native-settings]].
- **Defer to user judgment on script examples.** Propose rules and structure; don't write finished example hooks. [[feedback-script-voice]].
- **Keep disabled placeholder UI.** TopNav `/channels` and `/tools` links, disabled `/create` placeholder controls — all roadmap markers, leave alone. [[feedback-keep-placeholders]].
- **Content quality > feature breadth** until the user explicitly signals otherwise. Prompt work outranks UI work. [[project-content-quality-priorities]].
- **Per-channel learning, never global.** Sample pools and (future) edit-learning corpora are channel-scoped. Averaging across channels mushes voices. [[project-channel-presets]].
- **Measure, never proportionalize, time.** When mapping content to playback time, always anchor to real measured timestamps (ElevenLabs word alignment, file durations) — never word counts, character counts, or other proportional estimates. Four drift bugs found because this discipline was missing. New timing-aware code (editing/EDL/AI providers) inherits this constraint. See drift bug fixes section above.
- **Authority anchors opportunistic, never quota'd.** Use a named figure (with date + institution + consequence) ONLY when research actually has one. Skip otherwise — never invent or stretch one to satisfy a structural rule.
- **Caveat reframe = emphasis only, never magnitude.** Reframing "modest and inconsistent" as "the gentle nudge, not the main act" is fine. Reframing it as "the lift shows up reliably" inflates magnitude not in the source. Accuracy is sacred.

---

## Decision gates

- **Round 1 prompts → Round 2 (research feedstock):** are hooks + segments visibly better after a few real runs? If no, more Round 1 iteration before adding new research fields.
- **Short-term content → Medium-term polish:** are the videos consistently good enough that the friction in the per-video UI is the next bottleneck? If no, more prompt iteration before features.
- **Per-video polish → AI providers:** has the manual override + scene editor surfaced enough about what visual-providers should do that an AI provider can be designed with intent? If no, more polish first.
- **Per-video flows → Video editing stage:** have you edited several videos manually and noticed common patterns worth automating? If no, the learning corpus doesn't exist yet.

---

## What's NOT on the roadmap (intentionally deferred)

- **Removing disabled placeholders.** All planned channel-preset slots — leave alone.
- **Removing TopNav `/channels` and `/tools` links.** Roadmap markers (`/channels` is now real).
- **Single-canonical-entry-point question.** Both `/create` and "New project" coexist now, backed by one shared component. Resolution comes when `/create` repurposes (post Phase 6).
- **Dead legacy entry points** (`backend/pipeline.py`, `backend/main.py`, `backend/test-research.py`). Pre-frontend scripts; harmless. Delete during any cleanup pass if it comes up.
- **Channel-neutralizing the structure modules** further. Light gardening flavor remains in `script_modules/listicle.md` ("feeds the plant" example). Not load-bearing; fix when adding a second channel.
- **Script-stage RunPanel hydration.** Fix 2 covers voiceover/visuals/render; script-stage in-flight logs are lost on slug migration. Underlying task still runs; user refreshes to see the final result. Out of scope until it becomes a real friction.
- **Backwards-compat for old projects** with sidecars lacking `stock_id`. Legacy projects might still see duplicate footage on a fresh fetch. Acceptable degradation; flush sidecars to fix.
- **Audit M1 + M3 right now.** Theoretical drift in `-shortest` mux + `-c copy` concat. Bounded; revisit if it bites.

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
- `feedback_script_voice.md` — gardening-channel voice rules (channel-scoped, not Aqua-wide) — needs update to reflect "calmly certain" + universal conviction composing on top
- `feedback_voice_native_settings.md` — in-clip vs between-clip rule
- `feedback_keep_placeholders.md` — don't propose removing inert roadmap UI

**To-be-written (capture lessons from the recent session):**
- `project_drift_bug_pattern.md` — four drift bugs, same shape every time; measure-don't-proportionalize discipline
- `project_script_quality_principles.md` — viewer-centered orientation, research-as-bottleneck, opportunistic authority, caveat-emphasis rule, two-archetype distinction
- `reference_github_repo.md` — repo URL, visibility, collaboration setup

---

**Bottom line for a fresh session:** All six planned script-stage phases are done, Round 1 of prompt-quality polish is live, the four worst drift bugs are fixed, three pipeline UX papercuts are gone, and the repo is public. Next priority is exercising Round 1 against real videos, then deciding Round 2 (research feedstock) based on what's still thin. AI providers and the video editing stage are the big long-term lifts, gated on having a stable per-video flow.
