import json
import os
import re

from services.voice_prep_service import _expand_numbers


def load_scene_plan(project_name: str) -> dict:
    with open(f"../projects/{project_name}/scene_plan.json") as f:
        return json.load(f)


def load_audio_timeline(project_name: str) -> list:
    with open(f"../projects/{project_name}/audio_timeline.json") as f:
        return json.load(f)


def _sentence_starts(all_words: list) -> list[int]:
    """Indices of words that begin a new sentence."""
    starts = [0]
    for i, w in enumerate(all_words[:-1]):
        if re.search(r'[.!?]$', w['word']):
            starts.append(i + 1)
    return starts


def _snap_back(idx: int, sentence_starts: list[int]) -> int:
    """Return the sentence-start index that is <= idx."""
    for s in reversed(sentence_starts):
        if s <= idx:
            return s
    return 0


def compute_scene_windows(project_name: str) -> list:
    """
    Assign a display window [start_time, end_time] to each scene by distributing
    word timestamps proportionally across scene narration word counts, then snapping
    each cut to the nearest preceding sentence boundary.
    """
    scenes = load_scene_plan(project_name)['scene_intent']
    timeline = load_audio_timeline(project_name)

    # Flat word list sorted by global_start
    all_words = sorted(
        (w for chunk in timeline for w in chunk['words']),
        key=lambda w: w['global_start']
    )

    sent_starts = _sentence_starts(all_words)
    n_words = len(all_words)

    # Proportional mapping: narration word count → audio word index range.
    # Use TTS-expanded word counts so they match the actual spoken audio (which
    # was generated from tts_script.json where numerals are already expanded).
    narration_counts = [len(_expand_numbers(s['narration']).split()) for s in scenes]
    total_narration = sum(narration_counts)

    cumulative = 0
    word_indices = []
    for count in narration_counts:
        raw_idx = int(cumulative / total_narration * n_words)
        snapped = _snap_back(raw_idx, sent_starts)
        word_indices.append(snapped)
        cumulative += count

    # Deduplicate: if two scenes snapped to the same index, advance the later one
    # to the next sentence start so no scene gets 0 duration.
    for i in range(1, len(word_indices)):
        if word_indices[i] <= word_indices[i - 1]:
            later = [s for s in sent_starts if s > word_indices[i - 1]]
            word_indices[i] = later[0] if later else word_indices[i - 1] + 1

    # Build windows: each scene ends where the next begins
    result = []
    for i, scene in enumerate(scenes):
        start_idx = min(word_indices[i], len(all_words) - 1)
        start_time = all_words[start_idx]['global_start']

        if i + 1 < len(scenes):
            end_idx = min(word_indices[i + 1], len(all_words) - 1)
            end_time = all_words[end_idx]['global_start']
            # If deduplication collapsed adjacent scenes to the same word,
            # fall back to the end of that word so duration is never zero.
            if end_time <= start_time:
                end_time = all_words[end_idx]['global_end']
        else:
            end_time = all_words[-1]['global_end']

        result.append({
            **scene,
            'start_time': round(start_time, 3),
            'end_time': round(end_time, 3),
            'duration': round(end_time - start_time, 3),
        })

    return result


def save_scene_windows(project_name: str, windows: list):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/scene_windows.json", "w") as f:
        json.dump(windows, f, indent=2)


def load_scene_windows(project_name: str) -> list:
    with open(f"../projects/{project_name}/scene_windows.json") as f:
        return json.load(f)
