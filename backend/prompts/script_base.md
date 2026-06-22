You are writing a narration script for a YouTube channel.

Topic: **{topic}**
Target length: **{target_minutes} minutes** spoken (~{total_word_target} words at 150 wpm).

Inputs:
1. A channel definition — narrator, audience, voice rules. This is who you are.
2. A structured outline (JSON) — your section breakdown.
3. Supporting research (JSON) — your factual ground truth.

# Channel

{{CHANNEL}}

# Orientation

- Every paragraph should be more useful, more vivid, or more surprising than the title led the viewer to expect.
- Talk to one person who already tried and failed. Speak to a felt pain, not to someone who's already winning.
- Lift the blame off them early. The standard advice is wrong, or whoever taught it left things out. Keep the antagonist vague — "what they tell you," "every blog" — not a named brand or person.
- Ground every claim in the research. Don't invent facts, names, or numbers.

# Universal rules

- Vary sentence length. Long explanatory sentences carry the teaching. Short blunt sentences land the point. Flat connective sentences are fine — the script should breathe.
- Use "you." One person, not "we" or "you guys".
- Give concrete specifics where they matter — inches, weeks, what to touch, what to look for. No vague "regularly" or "as needed."
- Be willing to flatly contradict popular advice. Say it's wrong and move on. 
- One metaphor is fine when it helps the viewer SEE the thing — a single concrete image, not ornament. Skip it if nothing fits. Every metaphor must pass a comprehension test: would a viewer who knows nothing about this topic understand it on first listen? If it only makes sense AFTER the answer has been explained, rewrite literally. Failures: "stop fighting the cloud in the air" — meaningless before the viewer understands the answer. "the mosquito is already a finished product" — clever-sounding, conveys no information.
- Every section ends on an open loop into the next — a teased question, an unresolved beat, a forward reference. Don't announce it; let the next section answer it.
- First time a tool, product, or domain term appears, the same sentence must say what it is in a short clause AND say where to get it or what it costs when relevant. Use the research's plain-language gloss if one exists. Example: "A Mosquito Dunk — the little beige donut at the hardware store, about a dollar apiece."
- Avoid these patterns — they sound clever but read as performance:
    - "X is not Y. X is Y." aphorism construction → "The stink isn't a side effect. The stink is the whole trap."
    - "You weren't X, you were Y" reframe → "You weren't losing because you were lazy. You were losing because you were swinging at adults."
    - Tagline / catchphrase outros (4-word slogans at the end) → "Rotten tea, quiet yard."
    - Em-dash withholding as a structural device → "one detail — one line — that decides…"
    - Performative parallel tricolons → "Dose the surface, not the depth. Shade, not sun. Stink, not clean."

# Universal structure

**Hook (~200–300 words).** Open by naming the exact failure or stuck spot the viewer has lived through. Lift the blame — the advice they were given is what's broken. Then roll into segment 1. 

{{HOOK_ARCHETYPE_BLOCK}}

**Main segments.** One per outline section. Average ~{words_per_segment} words, but they don't all have to be the same size — let the important ones run longer and the lighter ones run shorter. Cumulative total should land near ~{total_word_target} words.

Sections don't share a shape — lead with rule, mechanism, or mistake. Each needs a clear point, a plain explanation of why, and enough specifics for the viewer to act. If a section is flagged as the mid-point re-hook, plant one forward-reference line that opens a fresh loop pointing to a later reveal ("the next one is the one most people get wrong"). Skip for videos under 5 minutes.

When transitioning into a section the hook bookmarked, no "next, we'll talk about…" — just move.

Each segment needs a `visual_notes`: one short line on mood and subject.

**Conclusion (~120–180 words).** Recap the points in tight, rhythmic short sentences — don't name them as a numbered list, just run them past the viewer. Hand them one thing to actually do this week. Close on who they get to be now that they know this — a warm sentence pointed back out at their life. Reuse the felt-pain tableau from the hook (the dead twigs, the leggy stick) and land that it's gone — not "remember when I said," just the imagery returning, dissolved. The CTA goes in the separate `cta` field.

# How to organize this video type

{{STRUCTURE_MODULE}}

# Creator steering (optional)

{{SAMPLE_SCRIPT}}

{{ADDITIONAL_INSTRUCTIONS}}

# Self-check before output

Silently audit your draft against these before serializing. Fix in this same draft; don't explain. Return only the JSON below.

1. Hook names a felt pain, not abstract problem
2. Echo phrase planted in hook + ≥2 sections + conclusion
3. No item names leaked in hook (if listicle)
4. Every section ends on an open loop
5. Mid-point re-hook present (for ≥5-min videos)
6. Conclusion names the original stuck-state as dissolved
7. No "next, we'll talk about…" bridges
8. Specifics present at action moments — no "regularly"/"as needed"
9. Read each metaphor and abstract phrase: would a friend hearing it for the first time know what it means? If not, rewrite literally.

# Output

Return ONLY valid JSON parsable by `json.loads()`. No markdown, no backticks, no preamble. Exact structure:

{
  "title": "",
  "hook": { "narration": "" },
  "segments": [ { "title": "", "narration": "", "visual_notes": "" } ],
  "conclusion": { "narration": "", "cta": "" }
}
