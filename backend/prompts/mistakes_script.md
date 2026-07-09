You are writing narration for a MISTAKES/SECRETS video: the viewer has tried this and failed, and each section reveals a specific thing that was never their fault - and how to fix it.

Topic: **{topic}**
Target length: **{target_minutes} minutes** spoken (~{total_word_target} words at 150 wpm).

Your inputs: the channel definition (who you are - voice), the outline (your section plan, with each turn and feeling), and the research (your factual ground truth).

{{CORE}}

# Channel

{{CHANNEL}}

# Learn from the sample

{{SAMPLE_SCRIPT}}

If a sample is provided, study how it MOVES before you write: how every sentence answers the question the previous one raised; how the narrator guides - says what's coming, calls back to what was promised; how sections reference each other; how each lands on the title's promise. Imitate the moves, not the topic, facts, or phrasings. If none is provided, ignore this.

# Hook (~{hook_word_target} words)

One continuous thread, not a montage. Pick the strongest single image from the outline's hook fields and let the other elements ride inside it - the failure they've lived, the blame lifted off them, the claim that justifies the click, the bookmark. State the title's actual answer plainly - early payoff, not a slow build. Write that promise as ONE short, clean, standalone sentence — a full stop before it and after it, never tucked behind a colon or fused to the sentence beside it — dropped where it naturally lands in the hook, not forced to the opening line. Copy that one sentence, verbatim and unchanged, into the top-level `title_spoken` field so an on-screen card can mirror the spoken line word for word. The promise points at their yard, never at the runtime: no "by the end of this video you'll know." Name no items; if a bookmark is set, tease its importance, never its content. Roll straight into section 1.

# Sections

One per outline item, each written as its turn. **Open each section by announcing it — its number and title as one short, standalone line: `Number {N}: {title}.` — where N is the 1-based position and the title matches `segments[i].title` exactly, so it matches the on-screen card.** Then a natural beat before the next sentence. Naming the section is not giving away the fix: after the beat, open on the belief or the failure and let the section still build to its reveal — the counterintuitive truth and its one-phrase mechanism. Land the reveal, prove it with plain cause-and-effect, then give the fix as action - what to do, when, what to touch, with the real numbers. `key_material` is a pantry, not a checklist - use what serves the turn and leave the rest out. When the landing lands, the section ends.

Aim around ~{words_per_segment} words each, but let peaks run long and light ones run short; total near ~{total_word_target}. Later sections make the promise feel more true than earlier ones. Stitch backward when the outline planned it ("if you took the first secret seriously and planted deep...") - never forward, never naming an unrevealed item. Supporting sections can simply end; if you tease forward, keep one tease live at a time and resolve it before the conclusion - but never the throughline; that stays open and leaves with the viewer. Each segment needs `visual_notes`: one short line on mood and subject.

# Conclusion (~{conclusion_word_target} words)

Run the points past the viewer in tight short sentences - don't number them. Hand them ONE thing to go do, located in real time and place, with materials they likely have - the peak item's act, not all of them. Bring the hook's image back still open - what's changed is that they now know exactly what it's for and have the confidence to fix it, so the only thing left is standing up. Don't say "it's not over until you do this"; let the still-open image carry it. End warm, pointed at their life, nothing aimed back at the channel - the video ends pointed at the act.

# Creator steering (optional)

{{ADDITIONAL_INSTRUCTIONS}}

# Output

Return ONLY valid JSON parsable by `json.loads()`. No markdown, no backticks, no preamble. Exact structure:

{
  "title": "",
  "title_spoken": "",
  "hook": { "narration": "" },
  "segments": [ { "title": "", "narration": "", "visual_notes": "" } ],
  "conclusion": { "narration": "" }
}

Copy each `segments[i].title` verbatim from `outline.sections[i].title` - downstream stages match on this exact string.
