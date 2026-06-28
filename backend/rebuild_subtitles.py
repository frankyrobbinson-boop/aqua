"""Fast iteration on subtitle styling: rebuild subtitles.ass from saved
audio_timeline.json and re-mux against the existing video_no_audio.mp4 +
full_audio.mp3.

Each run writes to the next available final_v<N>.mp4 (so prior versions stay
on disk for A/B comparison). Skips the slow footage-render + concat steps
entirely; only redoes the subtitle burn-in.

    python rebuild_subtitles.py <project_name>
"""

import os
import re
import sys

from services.assembly_service import mux_audio
from services.paths import PROJECTS_ROOT
from services.subtitle_service import build_subtitles


def _next_versioned_name(video_dir: str, prefix: str = "final") -> str:
    """Return next available final_v<N>.mp4 filename.

    If final.mp4 doesn't exist, return that. Else find max N from existing
    final_v<N>.mp4 files and return final_v{N+1}.mp4."""
    if not os.path.exists(f"{video_dir}/{prefix}.mp4"):
        return f"{prefix}.mp4"

    existing = []
    for fname in os.listdir(video_dir):
        m = re.match(rf"^{re.escape(prefix)}_v(\d+)\.mp4$", fname)
        if m:
            existing.append(int(m.group(1)))
    next_n = (max(existing) + 1) if existing else 2
    return f"{prefix}_v{next_n}.mp4"


def rebuild_subtitles(project_name: str) -> str:
    video_dir = str(PROJECTS_ROOT / project_name / "video")
    silent = f"{video_dir}/video_no_audio.mp4"
    audio = f"{video_dir}/full_audio.mp3"

    missing = [p for p in (silent, audio) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"Missing required intermediates: {missing}. "
            "Run run_video_only.py first to produce them."
        )

    print(f"[1/2] Rebuilding subtitles for '{project_name}'...")
    sub_path = build_subtitles(project_name, f"{video_dir}/subtitles.ass")
    print(f"      {sub_path}")

    output_name = _next_versioned_name(video_dir)
    print(f"\n[2/2] Re-muxing with new subtitles → {output_name}...")
    final = mux_audio(
        project_name, silent, audio,
        subtitle_path=sub_path,
        output_name=output_name,
    )
    print(f"\nDONE: {final}")
    return final


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    rebuild_subtitles(sys.argv[1])
