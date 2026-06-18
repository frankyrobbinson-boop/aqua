import json
import os
import re
from num2words import num2words

from services.tts_prep_service import load_tts_prep


_NUMBER_RE = re.compile(r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b')


def _convert_number(match: re.Match) -> str:
    raw = match.group(0).replace(",", "")
    # Treat 4-digit numbers in 1000-2099 range as years
    if re.fullmatch(r'\d{4}', raw) and 1000 <= int(raw) <= 2099:
        return num2words(int(raw), to="year")
    if "." in raw:
        return num2words(float(raw))
    return num2words(int(raw))


def _expand_numbers(text: str) -> str:
    """Expand numerals to words, skipping characters inside <break> tags."""
    parts = re.split(r'(<break\b[^>]*/?>)', text)
    return ''.join(
        p if p.startswith('<break') else _NUMBER_RE.sub(_convert_number, p)
        for p in parts
    )


def preprocess_text(text: str) -> str:
    text = re.sub(r'\[.*?\]', '', text)
    text = _expand_numbers(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def preprocess_for_delivery(text: str) -> str:
    """Normalize numbers and whitespace but keep [pause] markers for the delivery plan."""
    text = _expand_numbers(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_text(text: str, max_words: int = 75, min_last_words: int = 20) -> list[str]:
    """Split text into chunks of at most max_words, breaking only at sentence boundaries.
    If the final chunk would be too short, it's merged into the previous one."""
    sentences = _split_sentences(text)
    chunks, current, count = [], [], 0
    for sentence in sentences:
        wc = len(sentence.split())
        if count + wc > max_words and current:
            chunks.append(' '.join(current))
            current, count = [sentence], wc
        else:
            current.append(sentence)
            count += wc
    if current:
        chunks.append(' '.join(current))
    # Merge a short orphan tail into the previous chunk to avoid tiny trailing clips
    if len(chunks) > 1 and len(chunks[-1].split()) < min_last_words:
        chunks[-2] += ' ' + chunks[-1]
        chunks.pop()
    return chunks


def build_voice_units(project_name: str) -> list:
    script = load_tts_prep(project_name)
    units = []
    uid = 0

    for raw_chunk in _chunk_text(script["hook"]["narration"]):
        units.append({
            "id": uid, "type": "hook", "title": "Hook",
            "segment_key": "hook",
            "text": preprocess_text(raw_chunk),
            "delivery_text": preprocess_for_delivery(raw_chunk),
        })
        uid += 1

    for seg_idx, segment in enumerate(script["segments"]):
        for raw_chunk in _chunk_text(segment["narration"]):
            units.append({
                "id": uid, "type": "segment", "title": segment["title"],
                "segment_key": f"segment_{seg_idx}",
                "text": preprocess_text(raw_chunk),
                "delivery_text": preprocess_for_delivery(raw_chunk),
            })
            uid += 1

    for raw_chunk in _chunk_text(script["conclusion"]["narration"]):
        units.append({
            "id": uid, "type": "conclusion", "title": "Conclusion",
            "segment_key": "conclusion",
            "text": preprocess_text(raw_chunk),
            "delivery_text": preprocess_for_delivery(raw_chunk),
        })
        uid += 1

    return units


def save_voice_units(project_name: str, units: list):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/voice_units.json", "w") as f:
        json.dump(units, f, indent=2)


def load_voice_units(project_name: str) -> list:
    with open(f"../projects/{project_name}/voice_units.json", "r") as f:
        return json.load(f)
