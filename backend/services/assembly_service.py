import json
import os
import subprocess

from services.scene_timing_service import load_scene_windows, load_audio_timeline
from services.voice_service import CHUNK_GAP

FPS = 25
OUT_W, OUT_H = 1920, 1080


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def assemble_audio(project_name: str) -> str:
    """Concatenate audio chunks into a single MP3 with CHUNK_GAP silence between them."""
    timeline = load_audio_timeline(project_name)
    audio_dir = f"../projects/{project_name}/audio"
    video_dir = f"../projects/{project_name}/video"
    os.makedirs(video_dir, exist_ok=True)

    # Generate a short silence file used as gap filler
    gap_path = os.path.join(video_dir, "gap.mp3")
    if not os.path.exists(gap_path):
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"aevalsrc=0:c=mono:s=44100:d={CHUNK_GAP}",
            "-c:a", "libmp3lame", "-ar", "44100", gap_path,
        ], check=True, capture_output=True)

    # Build concat list: chunk, gap, chunk, gap, ...
    concat_path = os.path.join(video_dir, "audio_concat.txt")
    missing = [
        entry["audio_file"] for entry in timeline
        if not os.path.exists(os.path.join(audio_dir, entry["audio_file"]))
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing audio chunks — run audio generation first: {missing}"
        )

    with open(concat_path, "w") as f:
        for i, entry in enumerate(timeline):
            chunk_path = os.path.abspath(os.path.join(audio_dir, entry["audio_file"]))
            # Trim each file to speech_end so trailing ElevenLabs silence is excluded;
            # this keeps the assembled audio positions in sync with the timeline timestamps.
            chunk_duration = entry.get("speech_end", entry["duration"])
            f.write(f"file '{chunk_path}'\n")
            f.write(f"duration {chunk_duration}\n")
            if i < len(timeline) - 1:
                f.write(f"file '{os.path.abspath(gap_path)}'\n")
                f.write(f"duration {CHUNK_GAP}\n")

    out_path = os.path.join(video_dir, "full_audio.mp3")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-c:a", "libmp3lame", "-ar", "44100", out_path,
    ], check=True, capture_output=True)

    return out_path


# ---------------------------------------------------------------------------
# Scene clips (image + Ken Burns)
# ---------------------------------------------------------------------------

def _ken_burns(scene_idx: int, duration: float) -> str:
    """Alternate zoom-in / zoom-out expressions for zoompan."""
    frames = max(1, int(duration * FPS))
    if scene_idx % 2 == 0:
        # Zoom in: 1.0 → 1.1
        z = f"'min(1.1, 1.0 + 0.1*on/{frames})'"
    else:
        # Zoom out: 1.1 → 1.0
        z = f"'max(1.0, 1.1 - 0.1*on/{frames})'"
    x = f"'iw/2-(iw/zoom/2)'"
    y = f"'ih/2-(ih/zoom/2)'"
    return f"zoompan=z={z}:x={x}:y={y}:d={frames}:s={OUT_W}x{OUT_H}:fps={FPS},format=yuv420p"


def render_scene_clip(scene: dict, image_path: str, output_path: str):
    """Render one scene as a short video clip with a Ken Burns effect."""
    duration = max(0.1, scene['duration'])
    vf = _ken_burns(scene['id'], duration)

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        output_path,
    ], check=True, capture_output=True)


def render_all_scene_clips(project_name: str, image_paths: dict) -> list[str]:
    """Render every scene clip. Returns ordered list of clip paths."""
    windows = load_scene_windows(project_name)
    clips_dir = f"../projects/{project_name}/clips"
    os.makedirs(clips_dir, exist_ok=True)

    clip_paths = []
    for scene in windows:
        sid = scene['id']
        img_path = image_paths.get(sid)
        if not img_path or not os.path.exists(img_path):
            raise FileNotFoundError(f"No image for scene {sid}")
        out = os.path.join(clips_dir, f"scene_{sid:03d}.mp4")
        print(f"  Rendering clip: scene {sid}  ({scene['duration']:.1f}s)...")
        render_scene_clip(scene, img_path, out)
        clip_paths.append(out)

    return clip_paths


# ---------------------------------------------------------------------------
# Final assembly
# ---------------------------------------------------------------------------

def concat_clips(project_name: str, clip_paths: list[str]) -> str:
    """Join scene clips with the concat demuxer (hard cuts)."""
    video_dir = f"../projects/{project_name}/video"
    concat_path = os.path.join(video_dir, "clips_concat.txt")
    with open(concat_path, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    silent_video = os.path.join(video_dir, "video_no_audio.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-c", "copy", silent_video,
    ], check=True, capture_output=True)

    return silent_video


def mux_audio(project_name: str, video_path: str, audio_path: str) -> str:
    """Combine silent video with full audio track."""
    out = f"../projects/{project_name}/video/final.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        out,
    ], check=True, capture_output=True)
    return out


def assemble(project_name: str, image_paths: dict) -> str:
    """Full assembly: audio → clips → concat → mux → final.mp4"""
    print("  Assembling audio...")
    audio = assemble_audio(project_name)

    print("  Rendering scene clips...")
    clips = render_all_scene_clips(project_name, image_paths)

    print("  Concatenating clips...")
    silent = concat_clips(project_name, clips)

    print("  Muxing audio...")
    final = mux_audio(project_name, silent, audio)

    return final
