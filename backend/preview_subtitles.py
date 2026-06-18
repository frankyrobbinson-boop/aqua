"""Fast subtitle-style preview: rebuild subtitles.ass and mux only the first
60 seconds of the video. Lets you validate font/size/color/layout choices
without waiting for the full ~20-min libass burn-in over a 10-min video.

Output: ../projects/{project}/video/preview_v<N>.mp4 (next available slot
so previous previews stick around for comparison).

    python preview_subtitles.py <project_name> [duration_seconds]
"""

import os
import re
import sys

from services.subtitle_service import build_subtitles
from services.assembly_service import mux_audio


DEFAULT_PREVIEW_SECONDS = 60


def _next_preview_name(video_dir: str) -> str:
    if not os.path.exists(f"{video_dir}/preview.mp4"):
        return "preview.mp4"
    existing = []
    for fname in os.listdir(video_dir):
        m = re.match(r"^preview_v(\d+)\.mp4$", fname)
        if m:
            existing.append(int(m.group(1)))
    next_n = (max(existing) + 1) if existing else 2
    return f"preview_v{next_n}.mp4"


def preview_subtitles(project_name: str, duration: float) -> str:
    video_dir = f"../projects/{project_name}/video"
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

    output_name = _next_preview_name(video_dir)
    print(f"\n[2/2] Muxing first {duration:.0f}s preview → {output_name}...")
    final = mux_audio(
        project_name, silent, audio,
        subtitle_path=sub_path,
        output_name=output_name,
        duration_cap=duration,
    )
    print(f"\nDONE: {final}")
    return final


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    project = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PREVIEW_SECONDS
    preview_subtitles(project, seconds)
