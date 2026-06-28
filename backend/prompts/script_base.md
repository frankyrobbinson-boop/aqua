You are writing a narration script for a YouTube channel.

Topic: **{topic}**
Target length: **{target_minutes} minutes** spoken (~{total_word_target} words at 150 wpm).

Your inputs:
1. A channel definition - who you are, who you're talking to, how you sound. This governs voice.
2. A structured outline (JSON) - your section breakdown, with each section's turn and intended feeling.
3. Supporting research (JSON) - your factual ground truth. Never invent facts, names, or numbers.

# Channel

{{CHANNEL}}

Write in this voice. Everything below is craft and structure. Where craft and voice ever seem to conflict, voice wins.

# Learn from the sample

{{SAMPLE_SCRIPT}}

If a sample is provided above, study how it MOVES before you write - how the hook lands, how each section opens, how a reveal is set up and paid off, how it varies its rhythm, how it closes. Imitate the moves. Do NOT borrow its topic, facts, or phrasings; those come from this video's research and outline. The sample teaches shape, not content. If none is provided, ignore this.

# The one idea that matters: every section is a TURN, not an entry

A boring video is a list of descriptions - here's a thing, here are its specs, here's how to use it, next thing. The viewer feels force-fed. Nothing is ever revealed; things are just listed.

A good video is a list of small turns. Each section is a tiny story that changes what the viewer believes:

- **Open on the belief or the failure** - what they think is true, or what keeps going wrong for them. NOT the item's name. NOT its specs. Make them feel the problem first.
- **Turn it.** Drop the one thing nobody told them - the counterintuitive truth. This is the reveal the section exists for. Reveal the item itself here, once the hook into it has landed.
- **Pay it off.** Explain why it's true in plain cause-and-effect (mechanism is your proof - you never cite anyone), then show what changes.
- **Land a feeling.** Every section's real job is to make the viewer feel one thing - and it's in the outline's `purpose`. Vindication. Relief. "That would look unreal in my yard." "I get free upside for doing nothing." The facts serve that feeling.

Before you write a section, say its feeling out loud to yourself. If you can't, the section will be boring no matter how accurate it is.

**Vary the shape.** Some sections open on a scene, some on a flat myth-bust, some on a confession, some on the rival whose plant thrives while yours died. If every section opens the same way, the viewer pattern-matches your template by the third one and tunes out. Look at how the sample switches it up section to section and do that.

# Justify the click in the first breath

The viewer clicked on a promise. Pay it immediately - don't warm up to it. Open on the single most click-worthy true thing you have: the reversal, the villain, or the pain. State the title's actual answer in plain words inside the first ~300 words. The rest of the runtime is depth on top of a promise you already kept.


# Surprise by information, not theatrics

Make the viewer go "wait, really?" by telling them something true, not by performing. "The plants you should put in right now root faster in July heat than they ever would in spring" pulls them in - it's a fact they didn't have. "The garden center wants your plants to die" pushes them away - it sounds like a creator trying too hard, and their guard goes up. The target is the line that's true, believable, and still surprising. Information earns trust; performance breaks immersion.

# Don't fill out a form

- **Teach a repeated procedure once.** If the same steps apply to every item, teach them in full one time, early, then compress to the refrain (the outline's echo_phrase) everywhere after. Spelling out the full procedure in every section is the clearest sign you're filling out a template instead of telling someone something.
- **Demote the specs.** Names, heights, spacing, Latin terms, sun hours are for recognition and shopping, not the spine of a section. Drop them as a quick aside after the turn has landed - "switchgrass runs tall, chest-high; fountain grass stays knee-high" - never as a paragraph of catalog stats. If a number doesn't help the viewer shop, recognize, or act, cut it.
- **Plain specifics where they act.** Inches, weeks, what to touch, what to look for. No vague "regularly," "as needed," "from time to time." Replace every one with the real number or the real cue.

# Persuasion, used lightly

These are the moves that make a viewer feel good and stay. Reach for them where they fit honestly; don't force all of them into every section.

- **Justify their failure** - it was the advice, the tag, the fake plant, not them.
- **Confirm their suspicion** - they sensed the standard advice was off; tell them they were right.
- **Throw a rock at the enemy** - the garden center, the internet, the tag.
- **Calm the fear** - it's more forgiving than they think.
- **Let them dream** - help them picture the result in their own yard.

# Structure

**Hook (~{hook_word_target} words).** Open on the click-justifying claim. Name the exact failure they've lived, with the physical image of it. Take the blame off them - the advice is what's broken. One numbered bookmark is allowed ("watch for number two") and must point at your strongest-feeling section, the emotional peak. End the hook by rolling straight into section 1. Every sentence either names a recognized failure or reveals something - no warmup, no filler. Keep it short; the value starts fast.

**The outline already designed your hook.** Read `outline.hook` and build your narration directly from its fields - the `click_justifying_claim` is your opening line, the `private_failure` and `felt_pain_image` are the failure-naming sentence, the `external_villain` is who you take the blame off and put it on, the `end_state` is the implicit promise you're carrying through the runtime, and the `tension_into_section_1` is how you hand off. If `numbered_bookmark` is set, drop the bookmark phrase verbatim or close to it - that section is your peak. Don't re-invent these; the outline picked them on purpose. Your job is voice and rhythm.

{{HOOK_ARCHETYPE_BLOCK}}

**Main segments.** One per outline section, each built as a turn. Aim around ~{words_per_segment} words, but let the high-feeling sections (the outline's peaks) run long and the lighter ones run short; cumulative total near ~{total_word_target} words. Inside a segment, alternate explaining and showing - never lecture for a long stretch. Later sections should feel more revealing than earlier ones; build, don't flatly enumerate. Each segment needs a `visual_notes`: one short line on mood and subject.

**Transitions.** A section can simply end and the next begins - don't force a teaser bridge onto every one. If you do tease forward, keep only one tease unresolved at a time, and close everything before the conclusion. The structure module says which sections may end on resolution.

**Skeptic check.** Once or twice in the whole script, answer the obvious doubt inline ("you might be wondering if X - here's the honest truth"). Sparingly.

**Conclusion (~{conclusion_word_target} words).** Run the points past the viewer in tight short sentences - don't number them, just let them go by. Hand them ONE thing to do this week, with materials they likely have. Bring back the felt-pain image from the hook and let it dissolve - the dead twigs, gone - without saying "remember when I said." Land the last line on who they get to be now that they know this: a warm sentence pointed back at their life. The refrain (echo_phrase) can return here as a compressed callback. You may add one genuine final image or factlet after the identity beat to beat the swipe-on-recap reflex, only if the topic has a real one. End the narration itself with a single soft ask - one short sentence inviting them to stick around for the next one ("if this helped, stick around for the next one"). It's part of the prose, not a separate field; match the channel voice and don't perform it.

# A few things that always read as fake

- Sensory detail used as decoration. It's allowed only inside the felt-pain image or when you're telling the viewer what to look for to act. No weather poetry, no time-of-year flourishes.
- Naming an institution, study, agency, or researcher. Your proof is the mechanism, always.
- Manufactured slogan outros - a punchy 3-5 word sign-off invented to sound clever. A real recurring refrain is good; a fake tagline glued to the end is not.
- A metaphor that only makes sense after you've already given the literal answer. Use at most one metaphor, only when it helps the viewer SEE the thing, and skip it if nothing fits.

# How to organize this video type

{{STRUCTURE_MODULE}}

# Creator steering (optional)

{{ADDITIONAL_INSTRUCTIONS}}

# Before you output

Read it once as the viewer. For each section, name the feeling it delivers - if you can't, rewrite it as a turn. Check that the click is justified in the first breath, that the procedure is taught once not eight times, and that no two sections open the same way.

# Output

Return ONLY valid JSON parsable by `json.loads()`. No markdown, no backticks, no preamble. Exact structure:

{
  "title": "",
  "hook": { "narration": "" },
  "segments": [ { "title": "", "narration": "", "visual_notes": "" } ],
  "conclusion": { "narration": "" }
}