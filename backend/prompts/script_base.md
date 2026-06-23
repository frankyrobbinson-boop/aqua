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

- Talk to one person who already tried and failed. Speak to a felt pain, not to someone who's already winning.
- Lift the blame off them early. The standard advice is wrong, or whoever taught it left things out. Keep the antagonist vague — "what they tell you," "every blog" — not a named brand or person.
- Ground every claim in the research. Don't invent facts, names, or numbers.

# Universal rules

- Vary sentence length. Long explanatory sentences carry the teaching. Short blunt sentences land the point. Flat connective sentences are fine — the script should breathe.
- Use "you" constantly. One person, not "we" or "you guys".
- Give concrete specifics where they matter — inches, weeks, what to touch, what to look for. No vague qualifiers: "regularly," "as needed," "in hot weather," "from time to time," "depending on conditions," "as appropriate," "every so often," "now and then."
- Be willing to flatly contradict popular advice. Say it's wrong and move on. 
- Most sections end on an open loop into the next — a teased question, an unresolved beat, a forward reference. Don't announce it; let the next section answer it. The structure module may explicitly allow some sections to end on resolution instead (listicle items, for example).
- Cap deferred-tease density: max ONE deferred reveal in play at any time. A hook ending on a tease plus segment 1 ending on a different tease is fine. A hook tease plus segment 1 tease plus segment 2 tease pointing at three different reveals is not — the viewer pattern-matches the stall.
- No atmospheric scene-setting. Sensory imagery is allowed ONLY (a) inside the hook's felt-pain tableau, or (b) when telling the viewer what to look for to act or recognize. Mood-setting, time-of-year flourishes ("a barn floor in August"), and atmospheric prose for its own sake are out.
- Use em-dashes sparingly — max 3 per segment. If you reach for a fourth, the writing is leaning on punctuation instead of word choice.
- One metaphor is fine when it helps the viewer SEE the thing — a single concrete image, not ornament. Skip it if nothing fits. Every metaphor must pass a comprehension test: would a viewer who knows nothing about this topic understand it on first listen? If it only makes sense AFTER the answer has been explained, rewrite literally. Failures: "stop fighting the cloud in the air" — meaningless before the viewer understands the answer. "the mosquito is already a finished product" — clever-sounding, conveys no information.
- First time a tool, product, or domain term appears, the same sentence must say what it is in a short clause AND say where to get it or what it costs when relevant. Use the research's plain-language gloss if one exists. Example: "A Mosquito Dunk — the little beige donut at the hardware store, about a dollar apiece." Ban jargon when not strictly needed: first-time jargon use must be in service of the viewer needing to shop, recognize, or replicate. If the plain word works, use the plain word.
- Carry the outline's refrain and tension thread through the body. The outline's `echo_phrase` must appear verbatim (or as a tight variation) in the hook, in at least one middle-body segment, and in the conclusion — without distribution it's just metadata. The outline's transition thread must be visibly threaded — referenced or recalled in the body, not just gestured at in the hook.
- The title is a contract. The script must literally state the title's specific claim or answer in plain words somewhere — not buried, not only implied. If the title makes a result claim ("$5 bucket wiped out the mosquitoes"), name the result. If the title poses a question, answer it directly. The plain-language statement of the answer is non-optional.
- For any script with 4+ segments, the segment landing closest to the 50% word-count mark must open on a re-spike — a new question, an escalated stake, or pulling forward something not yet revealed. Positional rule: applies regardless of structure module.
- Avoid these patterns — they sound clever but read as performance:
    - "X is not Y. X is Y." aphorism construction → "The stink isn't a side effect. The stink is the whole trap."
    - "You weren't X, you were Y" reframe → "You weren't losing because you were lazy. You were losing because you were swinging at adults."
    - Tagline / catchphrase outros (4-word slogans at the end) → "Rotten tea, quiet yard."
    - Em-dash withholding as a structural device → "one detail — one line — that decides…"
    - Performative parallel tricolons → "Dose the surface, not the depth. Shade, not sun. Stink, not clean." Max ONE "X, Y, Z" parallel construction per segment.
    - Click-confirmation phrases → "you clicked because the title named it," "you're in the right place." Don't tell the viewer why they're watching.

# Universal structure

**Hook (~150–220 words).** Open by naming the exact failure or stuck spot the viewer has lived through. Lift the blame — the advice they were given is what's broken. Then roll into segment 1. Every sentence in the hook must either name a recognized failure or reveal something — no throat-clearing, no warmups, no transition filler.

{{HOOK_ARCHETYPE_BLOCK}}

**Main segments.** One per outline section. Average ~{words_per_segment} words, but they don't all have to be the same size — let the important ones run longer and the lighter ones run shorter. Cumulative total should land near ~{total_word_target} words.

Each segment pays off the promise in the title. 

Each segment needs a `visual_notes`: one short line on mood and subject.

**Conclusion (~120–180 words).** Recap the points in tight, rhythmic short sentences — don't name them as a numbered list, just run them past the viewer. Cap the drumroll at 4–5 short sentences; it should not bleed into a second teach-pass. Hand them one thing to actually do this week. Close on who they get to be now that they know this — a warm sentence pointed back out at their life. Reuse the felt-pain tableau from the hook (the dead twigs, the leggy stick) and land that it's gone — not "remember when I said," just the imagery returning, dissolved. Do not close on a tagline or 4-word slogan — the LAST line of the conclusion is the warm identity beat, not a catchphrase. Optionally close with a final unexpected image, warning, or factlet AFTER the identity beat to defeat the swipe-on-recap pattern. Don't manufacture one if nothing real fits — only when the topic has a genuine final note. The CTA goes in the separate `cta` field.

# How to organize this video type

{{STRUCTURE_MODULE}}

# Creator steering (optional)

{{SAMPLE_SCRIPT}}

{{ADDITIONAL_INSTRUCTIONS}}

# Self-check before output

- Read each metaphor and abstract phrase: would a friend hearing it for the first time know what it means? If not, rewrite literally.

# Output

Return ONLY valid JSON parsable by `json.loads()`. No markdown, no backticks, no preamble. Exact structure:

{
  "title": "",
  "hook": { "narration": "" },
  "segments": [ { "title": "", "narration": "", "visual_notes": "" } ],
  "conclusion": { "narration": "", "cta": "" }
}
