import json
import math
import os
import subprocess

from services.scene_timing_service import load_scene_windows, load_audio_timeline
from services.subtitle_service import build_subtitles
from services.voice_service import CHUNK_GAP

FPS = 25
OUT_W, OUT_H = 1920, 1080
# Bump when filter math changes in a way that should invalidate cached clips
# (e.g., Ken Burns formula change, fade duration change). The boolean flags
# in the cache key only catch flag flips; raw filter changes need this knob.
_CLIP_CACHE_VERSION = 5

# Per-clip fade-in/out duration when transition="fade". 0.15s in + 0.15s out
# per clip keeps total video duration unchanged (audio stays in sync) and
# produces a soft dip-through-black between scenes.
FADE_DUR = 0.15

# Note: `speech_end` from the audio timeline is already trim-adjusted by
# voice_service (TRAILING_TRIM applied at timeline-stamp time). Do not subtract
# another trim here — that would drift the assembled audio off the timeline.


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def assemble_audio(project_name: str) -> str:
    """Concatenate audio chunks into a single MP3 with CHUNK_GAP silence between them.

    Uses the ffmpeg concat *filter* (not the concat demuxer) so each chunk decodes
    in its own stream and gaps are inserted as inline `anullsrc` segments inside
    the filter graph. This avoids two prior failure modes:
      1. Mixed-format inputs (MP3 chunks + WAV gap) crashing the demuxer's shared
         decoder with "Invalid data found when processing input".
      2. MP3-frame-quantized gaps (~26 ms granularity) drifting ~40 ms per gap
         from the sample-accurate timeline.

    Gap duration is sample-accurate because `anullsrc` is a synthesized PCM source
    inside the graph — `d=0.3` at 44100 Hz is exactly 13230 samples.
    """
    timeline = load_audio_timeline(project_name)
    audio_dir = f"../projects/{project_name}/audio"
    video_dir = f"../projects/{project_name}/video"
    os.makedirs(video_dir, exist_ok=True)

    missing = [
        entry["audio_file"] for entry in timeline
        if not os.path.exists(os.path.join(audio_dir, entry["audio_file"]))
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing audio chunks — run audio generation first: {missing}"
        )

    # Build -i input args and the filter_complex graph.
    # For each chunk i:
    #   [i:a] atrim=start=speech_start:end=speech_end, asetpts=PTS-STARTPTS,
    #         aresample=44100, aformat=channel_layouts=mono [c{i}]
    # Between consecutive chunks:
    #   anullsrc=r=44100:cl=mono:d=CHUNK_GAP [g{i}]
    # Then concat=n=2N-1:v=0:a=1 → post filter chain → [out].
    #
    # aresample + aformat normalize each chunk to 44.1 kHz mono before concat;
    # concat requires every input to share sample rate, channel layout, and
    # sample format. ElevenLabs `mp3_44100_128` is mono 44.1 kHz already, so
    # these are defensive no-ops — but they keep the graph robust if a chunk
    # ever ships stereo or at a different rate.
    input_args: list[str] = []
    chunk_filters: list[str] = []
    concat_labels: list[str] = []

    for i, entry in enumerate(timeline):
        chunk_path = os.path.abspath(os.path.join(audio_dir, entry["audio_file"]))
        inpoint = entry.get("speech_start", 0.0)
        outpoint = entry.get("speech_end", entry["duration"])

        input_args += ["-i", chunk_path]
        chunk_filters.append(
            f"[{i}:a]atrim=start={inpoint}:end={outpoint},"
            f"asetpts=PTS-STARTPTS,aresample=44100,"
            f"aformat=sample_rates=44100:channel_layouts=mono[c{i}]"
        )
        concat_labels.append(f"[c{i}]")
        if i < len(timeline) - 1:
            chunk_filters.append(
                f"anullsrc=r=44100:cl=mono:d={CHUNK_GAP}[g{i}]"
            )
            concat_labels.append(f"[g{i}]")

    n_segments = len(concat_labels)  # = 2N-1 for N>=2, = 1 for N=1
    concat_chain = (
        f"{''.join(concat_labels)}concat=n={n_segments}:v=0:a=1[concat];"
        f"[concat]dynaudnorm=f=200:p=0.85:s=20,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"alimiter=limit=0.891251:level=disabled[out]"
    )
    filter_complex = ";".join(chunk_filters) + ";" + concat_chain

    out_path = os.path.join(video_dir, "full_audio.mp3")
    # Filter chain on [concat] (left-to-right):
    #   dynaudnorm — smooth chunk-to-chunk loudness variance. p=0.85 leaves more
    #     headroom for loudnorm; s=20 reduces gain-pump artifacts.
    #   loudnorm   — single-pass EBU R128 to -16 LUFS / TP -1.5 (YouTube spec).
    #   alimiter   — belt-and-suspenders true-peak limiter at -1.0 dBFS so any
    #     residual clip from loudnorm's single-pass approximation is caught.
    #     ffmpeg 8.x expects `limit` in linear amplitude (0.0625–1.0), not dB —
    #     0.891251 ≈ 10^(-1/20), i.e. -1.0 dBFS.
    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-ar", "44100", out_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # capture_output swallowed ffmpeg's diagnostics on prior bugs (e.g. the
        # alimiter unit confusion). Surface stderr before re-raising so future
        # failures aren't silent.
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(f"ffmpeg failed assembling audio for {project_name}:\n{stderr}")
        raise

    return out_path


# ---------------------------------------------------------------------------
# Scene clips (stock footage trimmed + normalized)
# ---------------------------------------------------------------------------

def _clip_cache_path(output_path: str) -> str:
    return output_path + ".cache.json"


def _clip_cache_hit(
    scene: dict,
    footage_path: str,
    output_path: str,
    transition: str,
    ken_burns: bool,
) -> bool:
    """True iff a previously-rendered clip is still valid for these inputs."""
    cache_path = _clip_cache_path(output_path)
    if not (os.path.exists(output_path) and os.path.exists(cache_path)):
        return False
    if os.path.getsize(output_path) == 0:
        return False
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        cache.get("footage_mtime") == os.path.getmtime(footage_path)
        and abs(cache.get("duration", 0.0) - max(0.1, scene["duration"])) < 0.01
        and cache.get("out_w") == OUT_W
        and cache.get("out_h") == OUT_H
        and cache.get("fps") == FPS
        and cache.get("transition") == transition
        and cache.get("ken_burns") == ken_burns
        and cache.get("cache_version") == _CLIP_CACHE_VERSION
    )


def render_scene_clip(
    scene: dict,
    footage_path: str,
    output_path: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
):
    """Render one scene by trimming + scaling a stock-footage clip to OUT_W x OUT_H.

    Caches the result in a sidecar `.cache.json`: re-runs skip the ffmpeg pass
    when the source footage hasn't changed and the scene's target duration is
    the same. Drop the sidecar to force re-render (e.g. after changing encoder
    settings or output dimensions).

    If the source clip is shorter than the scene duration, it is looped via
    `-stream_loop`. Audio is dropped; the final mux supplies the narration.

    transition: "cut" (default) or "fade". "fade" appends 0.15s fade-in and
      0.15s fade-out against black to each clip; the concat demuxer then joins
      them unchanged so total duration is preserved (audio stays in sync).

    ken_burns: when True AND the source is a PNG (still image), append a
      zoompan slow zoom from 1.0 -> 1.15 over the clip's duration. MP4
      sources are untouched — re-encoding stock video via zoompan can
      introduce subtle stretching, and they already have motion."""
    duration = max(0.1, scene['duration'])

    if _clip_cache_hit(scene, footage_path, output_path, transition, ken_burns):
        return  # cache hit — output already valid

    is_png = footage_path.lower().endswith(".png")

    # Standard chain when Ken Burns is OFF (or source is video).
    # When Ken Burns is ON and source is a PNG, swap zoompan entirely
    # for a scale-with-eval=frame + center-crop + motion-blur chain.
    # zoompan's per-frame integer rounding of the crop center was the
    # root cause of the residual jitter (visible 1px jumps every few
    # frames); the `scale=eval=frame` filter does subpixel-accurate
    # interpolation per frame instead. tblend at 2x temporal sampling
    # smooths whatever rounding remains in the center-crop stage.
    if ken_burns and is_png:
        # 4x spatial supersample: render the entire Ken Burns chain at
        # 7680x4320 (4K) internally, lanczos-downscale to 1920x1080.
        # The integer-pixel crop rounding inside the chain becomes 0.25px
        # in output space — below the visible-jitter threshold once the
        # downsample smooths it. 2x was not enough.
        SUPER = 4
        FPS_HI = FPS * 2  # temporal supersample for motion blur
        sw, sh = OUT_W * SUPER, OUT_H * SUPER
        total_frames_hi = max(1, math.ceil(duration * FPS_HI))
        KB_END_ZOOM = 1.08
        denom = max(1, total_frames_hi - 1)
        # Scale grows uniformly per frame (aspect preserved via the
        # pre-fit scale to sw×sh). Crop offset hardcoded from frame
        # number `n` rather than `(iw-sw)/2`: crop's `iw` is cached at
        # the initial value (sw) so the iw-based expression evaluates
        # to 0 every frame -> top-left anchoring. Computing from n
        # directly forces per-frame center-tracking.
        zoom_expr = f"(1+{KB_END_ZOOM - 1:.4f}*n/{denom})"
        x_max = sw * (KB_END_ZOOM - 1) / 2  # 307.2 px at sw=7680, KB=1.08
        y_max = sh * (KB_END_ZOOM - 1) / 2  # 172.8 px at sh=4320
        filters = [
            f"scale={sw}:{sh}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={sw}:{sh}",
            f"fps={FPS_HI}",
            "format=yuv420p",
            (
                f"scale=w='{sw}*{zoom_expr}':h='{sh}*{zoom_expr}'"
                f":eval=frame:flags=lanczos"
            ),
            f"crop={sw}:{sh}:x='{x_max:.4f}*n/{denom}':y='{y_max:.4f}*n/{denom}'",
            "tblend=all_mode=average",  # blend pairs -> motion blur
            "framestep=2",                # drop every other -> back to FPS
            f"scale={OUT_W}:{OUT_H}:flags=lanczos",
        ]
    else:
        filters = [
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase",
            f"crop={OUT_W}:{OUT_H}",
            f"fps={FPS}",
            "format=yuv420p",
        ]
    # Fade applies to every clip regardless of source type. Fade-out start =
    # duration - FADE_DUR; clamp to 0 for very short clips so we never get a
    # negative start time.
    if transition == "fade":
        fade_out_start = max(0.0, duration - FADE_DUR)
        filters.append(f"fade=t=in:st=0:d={FADE_DUR}")
        filters.append(f"fade=t=out:st={fade_out_start}:d={FADE_DUR}")

    vf = ",".join(filters)

    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", footage_path,
        "-vf", vf,
        "-t", str(duration),
        "-an",  # drop the stock clip's audio
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        output_path,
    ], check=True, capture_output=True)

    # Write the cache sidecar AFTER the ffmpeg call succeeds so partial renders
    # don't get mistaken for cache hits.
    with open(_clip_cache_path(output_path), "w") as f:
        json.dump({
            "footage_mtime": os.path.getmtime(footage_path),
            "duration": duration,
            "out_w": OUT_W,
            "out_h": OUT_H,
            "fps": FPS,
            "transition": transition,
            "ken_burns": ken_burns,
            "cache_version": _CLIP_CACHE_VERSION,
        }, f)


def render_all_scene_clips(
    project_name: str,
    footage_paths: dict,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> list[str]:
    """Render every scene clip. Returns ordered list of clip paths."""
    windows = load_scene_windows(project_name)
    clips_dir = f"../projects/{project_name}/clips"
    os.makedirs(clips_dir, exist_ok=True)

    clip_paths = []
    cached = 0
    rendered = 0
    for scene in windows:
        sid = scene['id']
        src = footage_paths.get(sid)
        if not src or not os.path.exists(src):
            raise FileNotFoundError(f"No footage for scene {sid}")
        out = os.path.join(clips_dir, f"scene_{sid:03d}.mp4")
        if _clip_cache_hit(scene, src, out, transition, ken_burns):
            cached += 1
        else:
            print(f"  Rendering clip: scene {sid}  ({scene['duration']:.1f}s)...")
            render_scene_clip(
                scene, src, out, transition=transition, ken_burns=ken_burns,
            )
            rendered += 1
        clip_paths.append(out)

    if cached:
        print(f"  Reused {cached} cached clip(s); re-rendered {rendered}.")

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


def mux_audio(
    project_name: str,
    video_path: str,
    audio_path: str,
    subtitle_path: str | None = None,
    output_name: str = "final.mp4",
    duration_cap: float | None = None,
) -> str:
    """Combine silent video with full audio track. If a subtitle path is given,
    burn subtitles into the video (requires re-encoding).

    output_name: filename inside the project's video/ dir.
    duration_cap: if set, only encode the first N seconds (for fast previews).
    """
    out = f"../projects/{project_name}/video/{output_name}"

    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path]
    if subtitle_path:
        # ffmpeg's subtitles filter parses the path through libavfilter syntax;
        # using an absolute path avoids confusion with the cwd at filter time.
        abs_sub = os.path.abspath(subtitle_path)
        cmd += [
            "-vf", f"subtitles={abs_sub}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        ]
    else:
        cmd += ["-c:v", "copy"]
    cmd += [
        "-map", "0:v", "-map", "1:a",
        "-c:a", "aac", "-shortest",
    ]
    if duration_cap is not None:
        cmd += ["-t", str(duration_cap)]
    cmd += [out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def assemble(
    project_name: str,
    footage_paths: dict,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> str:
    """Full assembly: audio → clips → concat → subtitles → mux → final.mp4

    transition: "cut" (default) or "fade" — per-clip fade-in/out against black.
    ken_burns: when True, applies a slow zoom to PNG (still-image) scenes only.
    Both are per-render options; not persisted to project state."""
    if transition not in ("cut", "fade"):
        raise ValueError(f"transition must be 'cut' or 'fade', got {transition!r}")

    print("  Assembling audio...")
    audio = assemble_audio(project_name)

    print("  Rendering scene clips...")
    clips = render_all_scene_clips(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
    )

    print("  Concatenating clips...")
    silent = concat_clips(project_name, clips)

    print("  Building subtitles...")
    sub_path = build_subtitles(
        project_name,
        f"../projects/{project_name}/video/subtitles.ass",
    )

    print("  Muxing audio + burning subtitles...")
    final = mux_audio(project_name, silent, audio, subtitle_path=sub_path)

    return final
