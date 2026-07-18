You are writing narration for a DISCOVERY LIST: a set of items (tools, techniques, or varieties) the viewer is mostly meeting for the first time. Nobody failed here. Your job with each item is to introduce it, make them want it with real facts, and hand them the one thing that unlocks it.

Topic: **{topic}**
Target length: **{target_minutes} minutes** spoken (~{total_word_target} words at 150 wpm).

Your inputs: the channel definition (who you are - voice), the outline (your item plan, with each stance and feeling), and the research (your factual ground truth).

{{CORE}}

# Channel

{{CHANNEL}}

# Learn from the sample

{{SAMPLE_SCRIPT}}

If a sample is provided, study how it MOVES before you write: how every sentence answers the question the previous one raised; how the narrator guides; how items reference each other; how each lands on the title's promise. Imitate the moves, not the topic, facts, or phrasings. If none is provided, ignore this.

# Hook (~{hook_word_target} words)

One continuous thread, not a montage. Open on the want - the thing they've been living without, made visible with the gap_image - then the claim that these {item_count} exist and why nobody handed them over. State the title's actual promise plainly inside the first ~300 words. Write that promise as ONE short, clean, standalone sentence — a full stop before it and after it, never tucked behind a colon or fused to the sentence beside it — dropped where it naturally lands in the hook, not forced to the opening line. Copy that one sentence, verbatim and unchanged, into the top-level `title_spoken` field so an on-screen card can mirror the spoken line word for word. Keep the count honest: the spoken promise and its `title_spoken` copy must agree with the video's {item_count} items — never shrink or blur the number ("one or two," "a couple," "a few") when the video actually delivers {item_count}. The promise points at their life, never at the runtime: no "by the end of this video you'll know." Name no items and preview no item's trait or trick; if a bookmark is set, tease its importance, never its content. Roll straight into item 1.

{{HOOK_ARCHETYPE_BLOCK}}

# Items

**Open each item by announcing it as TWO short sentences — the subject's noun with its number, then its name: `{item_noun} number {N}. {name}.` (e.g. "Gadget number 1. Air Fryers.") — where `{item_noun}` is the singular noun for what the whole list is made of (Flower, Gadget, Dish, Move…), N is the item's 1-based position, and the name matches `segments[i].title` exactly (its natural spoken form, usually plural), so it matches the on-screen card. Use the SAME noun for every item, and copy it — capitalized and singular — into the top-level `item_noun` field.** Then a natural beat before the next sentence, so the announcement stands alone and what follows starts clean. Then the thing about it that earns its place - the surprising claim, where they've seen it without knowing its name, what it refuses to need. Never open an item on mystery; the fog of an unnamed subject is the opposite of easy to watch.

Each "introduce" item runs: name it → the surprising claim → make them want it → the one unlock. The desire beat is the heart: what it looks like in their space, anchored to a spot they actually have ("that corner they walk past every day"), what it gives them, what it doesn't ask of them - built from research facts, never invented detail. The unlock is the single number, timing, or placement that makes it work, given as plain action. A "vindicate" item (the outline marks the rare ones) runs as a small turn instead: the failure, the truth, the fix.

**Tell them what to do, not what to avoid.** Give the right way as clean action. One wrong-way is contrast; a catalog of don'ts is noise. If a warning genuinely matters (toxicity, invasiveness), say it once, plainly, as a placement decision - then move on.

If the outline marked an over-delivery, land it on the item that carries it — the extra beyond that item's basic sell, given late, not teased.

`key_material` is a pantry, not a checklist. When the item's landing lands - the promise coming true again, through what the item does - the section ends. Aim around ~{words_per_segment} words each; let the peaks run long, total near ~{total_word_target}. Later items make the want bigger and more clearly within reach. Stitch backward when the outline planned it ("set it up the same way you set up the first one") - never forward, never naming an unrevealed item. Items can simply end. Each needs `visual_notes`: one short line on mood and subject.

# Conclusion (~{conclusion_word_target} words)

Run the items past the viewer in tight short sentences - don't number them. Before the act, give them the one thing that makes all {item_count} worth more than any single item — the payoff of the whole set. That's the "and then some": the last thing they hear is that they got more than they came for. Hand them ONE act, located in real time and place: go get the peak item this week and put it in the spot they already have. Bring the gap_image back still open - the corner's still bare - but now they know exactly what it's for and what to put there, so the only thing left is standing up. Don't say "it's not over until you do this"; let the still-open image carry it. End warm, pointed at their life, nothing aimed back at the channel - the video ends pointed at the act.

# Creator steering (optional)

{{ADDITIONAL_INSTRUCTIONS}}

# Output

Return ONLY valid JSON parsable by `json.loads()`. No markdown, no backticks, no preamble. Exact structure:

{
  "title": "",
  "title_spoken": "",
  "item_noun": "",
  "hook": { "narration": "" },
  "segments": [ { "title": "", "narration": "", "visual_notes": "" } ],
  "conclusion": { "narration": "" }
}

Copy each `segments[i].title` verbatim from `outline.sections[i].title` - downstream stages match on this exact string.
