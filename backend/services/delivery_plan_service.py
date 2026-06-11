import re

from services.voice_prep_service import load_voice_units

MAX_BREAKS = 3
_VALID_BREAK = re.compile(r'^<break\s+time="\d+(?:\.\d+)?s"\s*/>$')


def _sanitize(text: str) -> str:
    """
    Prepare TTS-prepped text for ElevenLabs:
    - Convert [pause] markers
    - Strip other bracket markers
    - Remove malformed break tags (e.g. time="zero.7s" from number-expander corruption)
    - Strip breaks at chunk edges (ElevenLabs handles edge padding badly)
    - Cap to MAX_BREAKS (keep the first N — Claude put the most important ones first)
    """
    text = re.sub(r'\[pause\]', '<break time="0.6s"/>', text, flags=re.IGNORECASE)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Drop any break tag that doesn't have a clean numeric time value
    text = re.sub(
        r'<break[^>]*/>',
        lambda m: m.group(0) if _VALID_BREAK.match(m.group(0)) else '',
        text,
    )

    # Strip breaks at the start or end of the chunk
    text = re.sub(r'^(\s*<break[^>]*/>\s*)+', '', text).strip()
    text = re.sub(r'(\s*<break[^>]*/>\s*)+$', '', text).strip()

    # Keep only the first MAX_BREAKS breaks
    count = 0
    def _cap(m):
        nonlocal count
        count += 1
        return m.group(0) if count <= MAX_BREAKS else ''
    text = re.sub(r'<break[^>]*/>', _cap, text)

    return text


def annotate_unit(unit: dict) -> str:
    return _sanitize(unit.get('delivery_text', unit['text']))


def build_delivery_plan(project_name: str) -> list:
    units = load_voice_units(project_name)
    for unit in units:
        print(f"  Annotating: {unit['title']}...")
        unit['ssml'] = annotate_unit(unit)
    return units
