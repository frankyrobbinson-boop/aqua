# Aqua — Goals (last updated 2026-06-28)

## North star

Aqua is being built to make the best AI movies — short narrative films first, then features. The YouTube pipeline that exists today is the easy case of the same tool: if you can carry a character, a setting, and an emotional arc across decades of in-story time, a 12-minute listicle is trivial. Nobody is aiming there. We are. YouTube remains a first-class output, but every architectural decision from here forward is graded against whether it scales to a narrative film.

## What "real movies" means here

- Single narrator over AI-generated visuals is the entry form, not the ceiling. Think narrated short film (the kind that screens at festivals as a 10-15 minute piece), not slideshow.
- A few minutes to ~90 minutes long. Hierarchical structure (act → sequence → scene → shot), not a flat segment list.
- Multiple voices when the story needs them; consistent characters and settings across the entire runtime; music and ambience layered against dialogue.
- AI does the heavy lifting; a human directs and approves the load-bearing creative choices (character anchors, pacing, chapter cuts). Heavy human-in-the-loop early, less over time as model quality and our tooling both climb.
- Not a Hollywood feature with a $20M budget and 200-person crew. Somewhere between an animated short and an indie feature, grounded in what Nano Banana, Veo 3.1, Gen-4 References, ElevenLabs v3, Suno, and Stable Audio can plausibly do in 2026-2028.

## The first concrete target: "The Perennial"

"The Perennial" is a short story the user wrote — first-person narration from a perennial flower watching the same garden across decades. The woman tends; the woman ages; the woman is gone; a child returns. It is the right v1 target because it pressure-tests every hard problem at once:

- **Time scale.** Decades pass between scenes. The garden ages with the story.
- **Character continuity.** The woman at 30, 60, gone. The same bloom across many shots. The garden in spring, in wild years, in a new beginning.
- **Quiet pacing.** Beats hold. Long silences over wind. Nothing in today's pipeline can express a 6-second pause.
- **Emotional arc.** Lands on quietness, not payoff. No villain, no click to justify, no CTA.

**V1** is The Perennial as a 10-15 minute narrated short film: single voice, AI-generated stills with Ken Burns + crossfades, ambient bed + soft score, character/setting continuity locked through anchor images. **V2** expands to dialogue (the woman speaks; the child speaks). **V3** is the Toy-Story-style talking-flowers variant — every named bloom has a voice and a face — at short-film length first, then feature.

The canonical text lives at `references/source_stories/the_perennial.md` (written during the pivot analysis). Production notes live in that file's header; the chapter structure is preserved so a future stage can split by chapter without re-parsing prose.

## Phased trajectory

### Phase 0 — Now: 10-15 min narrated YouTube videos

- **Goal.** Consistently good single-narrator listicles, deep-dives, and stories on the gardening channel and future channels.
- **Built.** All six script-stage phases (channel registry, hook archetypes, channel UI). Round 1 prompt-quality polish. Four drift bugs fixed. Stage-graph (`backend/services/stage_graph.py`) with cascade invalidation and content-keyed sidecars. Parallel visuals + voice. Per-clip render cache. ElevenLabs single-voice via `voice_service.py` + `voice_elevenlabs.py`. Pexels + Nano Banana via `visual_provider.py` registry. EDL v1 in `edl_service.py`. ASS karaoke subtitles. Cost ledger in `cost_ledger.py`. Public repo at `github.com/frankyrobbinson-boop/aqua`.
- **Build.** Script-stage Phase 7 (channel sample pool). Script-quality Round 2 (research-stage feedstock) if Round 1 still feels thin after more real runs. Stock-footage provider swap. Per-segment AI visuals policy.
- **HITL.** User edits script in-UI; user reruns voiceover/visuals/render; user spot-fixes individual scenes.
- **Litmus test.** A gardening listicle the user is willing to publish without script edits.

### Phase 1 — First narrated short film: "The Perennial V1"

- **Goal.** A 10-15 minute single-narrator narrative film with locked character + setting continuity.
- **Build (the 4-5 targeted additions).**
  1. New `narrative_film` video_type — `prompts/video_types.json` + `prompts/script_modules/narrative_film.md` + `prompts/outline_modules/narrative_film.md`. Bypasses hook/villain/CTA; script stage becomes a thin formatter over user-edited source text rather than a generator.
  2. New `prompts/scene_plan_film.md` + sibling service. Drops the 5-9s ceiling. Adds `present_characters`, `state_variant`, `dwell_seconds`, `shot_type`, `ambient_bed_id` to the per-scene schema. Defaults `visual_mode` to AI image, never stock.
  3. Pause-marker contract end-to-end (`[pause:6]` honored by `voice_prep_service` and `assembly_service` as sample-accurate silence in the audio_timeline).
  4. Cast/world manifest at the project level — `projects/<slug>/cast.json` + `projects/<slug>/locations.json` with `anchors_by_state` per entity. New `cast_anchors` pipeline stage between scene_plan and visuals: generates a turnaround anchor per character/state and per location. `VisualProvider.fetch_for_scene` grows a typed `reference_images` field; `NanoBananaProvider._generate` is wired to pass `inline_data` parts (today it only sends a prompt string). This is the single load-bearing change.
  5. Three-track audio mix — narration + ambient bed (per-chapter or per-scene) + score (Suno or Stable Audio cue), with sidechain ducking on the narration envelope. Subtitles flip to sidecar-not-burned for `narrative_film`; per-scene overlay text defaults to null.
- **HITL.** User approves the character anchors (1 review per character per state, then ~80 scenes inherit). User reviews chapter-level edits and per-scene image regenerations. User tunes pause durations.
- **Litmus test.** The Perennial V1 — a watchable 10-15 minute short film where the bloom is recognizably the same bloom in scene 5 and scene 80, the garden ages, the woman ages, and the silences land.

### Phase 2 — Multi-voice short narrative

- **Goal.** Short narrative pieces with dialogue (the woman speaks, the child speaks), basic music + ambience scoring, multiple named characters.
- **Build.** `speaker` field on script lines and voice units. Cast block on the channel preset (`cast: {narrator: {...}, woman: {...}}`) resolved by `voice_service` per unit instead of per project. ElevenLabs v3 audio tags (`[whispers]`, `[sad]`) gated on opt-in. `MusicProvider` and `SFXProvider` abstractions as siblings to `VoiceProvider` (Stable Audio for cues, ElevenLabs SFX + Freesound for foley + ambience). EDL v2 with `audio_tracks` block (music/ambience/sfx). Dialogue-style subtitles with speaker labels.
- **HITL.** User casts each character (picks ElevenLabs voice clone or stock voice). User reviews dialogue beats — line-level rerolls per character.
- **Litmus test.** The Perennial V2 — same story, but the woman and the child have voiced lines, with ambient garden beds across seasons and a piano leitmotif for the bloom.

### Phase 3 — Feature-length scaffolding

- **Goal.** Architecture that can carry a 60-90 minute film without breaking — even if the first feature isn't rendered yet.
- **Build.** Persistent World Bible (`world_bible.json`) as a first-class artifact — characters, locations, props, timeline, motifs — spliced into every downstream LLM prompt the way `{{CHANNEL}}` is today. Hierarchical project layout (`acts/<id>/sequences/<id>/scenes/<id>/...`) with the stage-graph extended to per-act scope so editing act 2 doesn't reblow act 1's cache. Batched script generation (sequence-by-sequence with prior-context summary + bible as continuity carriers). Continuity-guard stage that diffs each new sequence against the bible and surfaces contradictions. Per-act audio render with concat-of-intermediates instead of one 700-input filter_complex. Pre-flight cost estimator + `MAX_PROJECT_USD` hard cap.
- **HITL.** User reviews each generated sequence before the next is generated. User edits the World Bible directly when continuity needs nudging.
- **Litmus test.** A 25-30 minute Perennial expansion across all chapters, generated in 3-4 sequence batches, with continuity holding across the batch seams.

### Phase 4 — Real feature production

- **Goal.** A 60-90 minute film — the Toy-Story-style Perennial, or an equivalent original.
- **Build.** AI motion video providers as new `VisualProvider` implementations (Veo 3.1 / Runway Gen-4 / Kling), conditioned on the locked anchor images, producing 5-10s clips that the existing render stage stitches the way it stitches stills today. Per-character voice aging (cast variants by chapter/sequence). EDL export to OpenTimelineIO so the final mix can move into Resolve or Reaper when ffmpeg becomes the wrong tool. The video editing learning loop from the existing roadmap kicks in: per-channel EDL corpus, AI predicts cuts/transitions/SFX placement.
- **HITL.** Lighter per-shot review; heavier review at sequence and act boundaries. User polishes the final mix in Resolve.
- **Litmus test.** A feature the user is willing to put their name on.

## Architectural shifts required (cross-cutting)

1. **Cast manifest (Phase 1).** `cast.json` per project. Replaces the channel preset's single-character block. Each entity has anchor images keyed by state variant (young/old, tended/wild). Cast is the entity registry; scenes tag which cast members appear.
2. **World/Location manifest (Phase 1).** `locations.json` per project, same shape — sets are first-class entities with their own anchors. Same garden, four seasons, three eras.
3. **Reference images flow end-to-end through `VisualProvider` (Phase 1).** Today `NanoBananaProvider._generate` sends a prompt string only; the Gemini SDK supports `inline_data` parts and the provider just doesn't use them. Typed `SceneRequest` with `reference_images`, `character_refs`, `location_refs`, `continuity_ref` (prior scene). Pexels ignores; AI providers consume.
4. **`narrative_film` video_type with its own scene_plan prompt (Phase 1).** Drops the YouTube structural rules (hook/villain/CTA, 5-9s scenes, stock-friendly nouns). Adds chapter shape, dwell ranges, present_characters per scene.
5. **Pause-marker contract (Phase 1).** Sample-accurate silence in `voice_prep_service` + `assembly_service`. Reuses the `anullsrc`-in-filter-graph pattern from the gap.mp3 drift fix.
6. **Three-track audio mix (Phase 1).** Extends `assemble_audio` from one-stream concat to narration + ambient + score buses with sidechain ducking. `MusicProvider` + `SFXProvider` abstractions added in Phase 2.
7. **Multi-voice cast on `VoiceProvider` (Phase 2).** `speaker` field on voice units. Channel preset's voiceover block grows to a dict of named voices. Per-unit voice resolution; request-id chaining keys on `(segment, speaker)` so each character's prosody chains independently.
8. **Director cues / delivery field on script lines (Phase 2).** Abstract `delivery` dict translated per provider — ElevenLabs v3 audio tags, Qwen3 emotion params.
9. **EDL v2 with `audio_tracks` (Phase 2).** Music/ambience/sfx cues live in the EDL alongside scene treatments. Existing `version` field already in place for this growth.
10. **Subtitle mode per video_type (Phase 1).** `narrative_film` defaults to sidecar; YouTube stays burned-in karaoke. Speaker labels + bracketed non-dialogue cues land in Phase 2.
11. **Persistent World Bible (Phase 3).** `world_bible.json` spliced into every LLM stage via `{{WORLD_BIBLE}}` slot. The composition machinery (`channel_registry.resolve_*`, `compose_script_prompt`) already has the right shape.
12. **Hierarchical project layout — acts/sequences/scenes/shots (Phase 3).** Stage-graph extends to per-act scope. Today's "scene" is renamed to "shot"; a film "scene" becomes a dramatic unit containing many shots.
13. **Batched script generation with continuity hand-off (Phase 3).** Sequence-sized batches; each call receives the World Bible + a structured summary of prior sequences. The Sonnet 4.6 single-call ceiling at ~25 minutes of script is a hard wall otherwise.
14. **Pre-flight cost estimator + hard project cap (Phase 3).** `estimate_run_cost(project, stages)` predicts ElevenLabs/Nano Banana/LLM spend before any stage starts. `MAX_PROJECT_USD` aborts a stage if running total crosses the cap.
15. **AI motion video providers + EDL→OTIO export (Phase 4).** Veo 3.1 / Gen-4 as new `VisualProvider` implementations behind the same `SceneRequest` interface. OpenTimelineIO export so the final mix can leave ffmpeg for a real DAW when it has to.

## Where the recent 6 bundles fit

The just-landed work — channel-aware script prompts, audio drift fixes, render correctness, visuals dedup + rerank, backend reliability + stage-graph, frontend per-video flow — is the substrate this vision builds on, not a previous chapter to be discarded. Phase 0 IS those bundles in production; everything from Phase 1 onward is additive.

Specifically: the **stage-graph** (`stage_graph.py`) absorbs new stages (`cast_anchors`, `world_bible`, `score`, `continuity_check`) by adding declarations, not rewrites. The **channel preset architecture** is the structural template for cast/world manifests — same composition pattern, richer entities. The **cost ledger** becomes the data source for the Phase 3 pre-flight estimator. The **drift-fix discipline** (measure, never proportionalize) ports verbatim to pause markers, ambient ducking, and continuity scoring. The **`VisualProvider` registry** is the right shape for adding Gen-4 and Veo as siblings to Nano Banana. The **stage-graph cascade invalidation with content-keyed sidecars** is what makes per-scene rerolls cheap at film scale.

## What we explicitly defer

- Hollywood-budget feature production (live actors, motion capture, on-set photography).
- Real-time or interactive generation. Aqua is a render pipeline, not a game engine.
- End-to-end agentic generation with zero human input at the feature scale. The user explicitly accepts heavy HITL early; Phase 4 lightens it but does not remove it.
- Building our own image/video foundation models. We compose providers.
- A theatrical-grade color/sound master pipeline. EDL→OTIO export is the escape hatch — Resolve does the final mix.

## How this changes today's work

Phase 0 is still where this week's work lives — Round 1 prompts against real videos, then Round 2 if needed. The pivot reframes today's roadmap as the substrate, not the destination, and adds Phase 1 as the next horizon after the current YouTube polish stabilizes. Nothing on `ROADMAP.md` becomes wrong; the long-tail items (per-segment AI visuals, video editing stage, EDL-driven assembly, channel preset expansion) all become Phase 1 or Phase 2 enablers.

## Next 3 concrete moves

1. **Plumb reference image bytes through `NanoBananaProvider._generate`** as `inline_data` parts, with a typed `reference_images` argument on `VisualProvider.fetch_for_scene`. *Phase 1 architectural keystone.* A 1-2 day change with zero new dependencies that unlocks character consistency on the provider we already pay for.
2. **Stand up the `narrative_film` video_type + `scene_plan_film` prompt** as a parallel path to listicle/story (not a refactor). *Phase 1 entry point.* Three new prompt files + a sibling service + one schema extension. The YouTube pipeline is untouched; the film pipeline boots beside it.
3. **Spike a cast/world manifest with anchor generation** on The Perennial — one character (the woman, two state variants: tended/aged) and one location (the garden, four state variants: spring/summer/wild/cleared). *Phase 1 proof.* This validates the manifest schema against a real story before generalizing.

(Step zero — persist The Perennial — is done. The text lives at `references/source_stories/the_perennial.md` with chapter markers and production notes.)

## Open questions

- **Should V1 of The Perennial be photoreal or stylized?** Photoreal stresses Nano Banana's identity preservation on non-human subjects (a specific bloom) — the harder, less-tested case. Stylized (illustrated, painterly) is more forgiving but commits to a look the user may not want for a contemplative piece.
- **One narrator voice or two?** The perennial herself is the narrator. Is there also a framing third-person voice (the user, looking back), or does the perennial carry the whole story alone? Affects Phase 1 vs Phase 2 boundary.
- **How do we source the score for V1?** Suno (vocal-quality finished cues, may overpower the contemplative tone) vs Stable Audio (instrumental stems we can shape into a leitmotif) vs a human composer for the v1 piece specifically.
- **What's the right unit for HITL review at Phase 1 — chapter, scene, or shot?** Chapter-level keeps friction low but means surprises when a render lands. Shot-level is the highest control but kills momentum. Best guess is chapter-level with shot-level reroll on demand.
- **Is the V2 multi-voice short the next milestone after V1, or do we go feature-length single-voice first?** Phase 3 scaffolding (World Bible, hierarchy, batched generation) is independent of multi-voice and might land sooner if the user wants a longer Perennial before a talking-flowers one.
- **Where does HITL on continuity actually want to live in the UI?** Phase 3's continuity-guard surfaces contradictions, but the existing `/projects/[slug]` workspace is YouTube-shaped. Probably needs a separate film workspace route by Phase 1 launch.
