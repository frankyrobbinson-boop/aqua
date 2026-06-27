import json
import math
import os
import subprocess

from services.edl_service import generate_default_edl, load_edl, save_edl
from services.scene_timing_service import load_scene_windows, load_audio_timeline
from services.subtitle_service import build_subtitles
from services.voice_service import CHUNK_GAP

FPS = 25
OUT_W, OUT_H = 1920, 1080
# Bump when filter math changes in a way that should invalidate cached clips
# (e.g., Ken Burns formula change, fade duration change). The boolean flags
# in the cache key only catch flag flips; raw filter changes need this knob.
# v6: per-scene EDL drives overlay_text + overlay_position; cache key now
# includes both so a text change invalidates only the affected clip.
_CLIP_CACHE_VERSION = 6

# Per-clip fade-in/out duration when transition="fade". 0.15s in + 0.15s out
# per clip keeps total video duration unchanged (audio stays in sync) and
# produces a soft dip-through-black between scenes.
FADE_DUR = 0.15

# Per-overlay fade-in/out duration (drawtext alpha ramp). 0.3s each side
# softens the entry/exit of text on screen without eating into legibility on
# short scenes (a 1.5s scene still gets ~0.9s of full-opacity text).
OVERLAY_FADE = 0.3

# Mac-only system fonts for the drawtext overlay. Portable font handling
# (bundle a TTF, fallback to a fontconfig family) is a future-phase concern;
# the only deployment today is the maintainer's Mac.
_OVERLAY_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _overlay_font_path() -> str | None:
    for p in _OVERLAY_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _escape_drawtext(s: str) -> str:
    """Escape a string for ffmpeg drawtext's text= argument.

    drawtext parses its text= value through libavfilter's option parser, which
    treats backslash, colon, single quote, and percent specially. We wrap the
    whole text in single quotes and escape any embedded single quotes via
    drawtext's own ``\\'`` escape, then escape the backslashes for the option
    parser. Newlines and other control chars are stripped — a single-line
    overlay is the only V1 layout."""
    cleaned = s.replace("\n", " ").replace("\r", " ")
    # Order matters: backslash first so we don't double-escape escapes we add.
    cleaned = cleaned.replace("\\", "\\\\")
    cleaned = cleaned.replace(":", "\\:")
    cleaned = cleaned.replace("'", "\\\\\\'")
    cleaned = cleaned.replace("%", "\\%")
    return cleaned


def _overlay_position_expr(position: str) -> tuple[str, str]:
    """Return (x_expr, y_expr) for drawtext given a position keyword.
    Defaults to top for unknown values rather than raising — overlays are
    cosmetic, a bad position string shouldn't kill the render."""
    if position == "center":
        return "(w-text_w)/2", "(h-text_h)/2"
    if position == "bottom":
        return "(w-text_w)/2", "h*7/8-text_h"
    # "top" (and fallback)
    return "(w-text_w)/2", "h/8"


def _build_overlay_filter(
    text: str,
    position: str,
    duration: float,
) -> str | None:
    """Build the drawtext filter expression for one scene's overlay, or None
    if no font is available (logged once per render)."""
    font = _overlay_font_path()
    if font is None:
        print(
            "  WARN: no overlay font found on this system; skipping text "
            f"overlay {text!r}. Tried: {_OVERLAY_FONT_CANDIDATES}"
        )
        return None
    x_expr, y_expr = _overlay_position_expr(position)
    text_esc = _escape_drawtext(text)
    # Alpha ramp: fade in 0.3s, hold, fade out 0.3s. Clamp the hold window so
    # very short scenes (< 2 * OVERLAY_FADE) just cross-fade in/out without a
    # negative-duration hold.
    fade = OVERLAY_FADE
    if duration <= 2 * fade:
        # Symmetric ramp up to mid, ramp down after — keeps legibility on tiny
        # clips without a flash of full opacity.
        half = duration / 2
        alpha = (
            f"if(lt(t,{half:.3f}),t/{half:.3f},"
            f"({duration:.3f}-t)/{half:.3f})"
        )
    else:
        out_start = duration - fade
        alpha = (
            f"if(lt(t,{fade}),t/{fade},"
            f"if(lt(t,{out_start:.3f}),1,"
            f"({duration:.3f}-t)/{fade}))"
        )
    parts = [
        f"text='{text_esc}'",
        f"fontfile='{font}'",
        "fontsize=64",
        "fontcolor=white",
        "box=1",
        "boxcolor=black@0.6",
        "boxborderw=20",
        f"x={x_expr}",
        f"y={y_expr}",
        f"alpha='{alpha}'",
    ]
    return "drawtext=" + ":".join(parts)

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
        f"[concat]loudnorm=I=-16:TP=-2:LRA=11[out]"
    )
    filter_complex = ";".join(chunk_filters) + ";" + concat_chain

    out_path = os.path.join(video_dir, "full_audio.mp3")
    # Single-filter chain on [concat]:
    #   loudnorm — EBU R128 to -16 LUFS / true-peak -2 dBFS / LRA 11.
    #
    # Previously chained dynaudnorm + loudnorm + alimiter. dynaudnorm's
    # rolling-window gain-pumping survived into loudnorm's "even" output as
    # audible breathing; single-pass loudnorm overshoots, so the alimiter
    # had to attenuate hard, sounding pumpy/compressed on speech.
    # TP=-2 (was -1.5) gives loudnorm 0.5 dB more headroom, eliminating
    # the need for the belt-and-suspenders alimiter. Result is cleaner
    # speech with no audible distortion from the equalization chain.
    #
    # MP3 bitrate bumped to 192k (libmp3lame default trends ~128k VBR);
    # ElevenLabs source is mp3_44100_128 already, so re-encoding at a
    # higher bitrate avoids compounding compression artifacts.
    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", out_path,
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
    overlay_text: str | None = None,
    overlay_position: str | None = None,
) -> bool:
    """True iff a previously-rendered clip is still valid for these inputs.

    overlay_text + overlay_position are part of the key so an EDL edit (e.g.
    changing 'Item 3: foo' to 'Item 3: bar') invalidates only the one
    affected scene, not the whole project's clip cache."""
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
        and cache.get("overlay_text") == overlay_text
        and cache.get("overlay_position") == overlay_position
        and cache.get("cache_version") == _CLIP_CACHE_VERSION
    )


def render_scene_clip(
    scene: dict,
    footage_path: str,
    output_path: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
    overlay_text: str | None = None,
    overlay_position: str = "top",
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
      introduce subtle stretching, and they already have motion.

    overlay_text: when non-None, append a drawtext filter rendering the text
      with a translucent black box at ``overlay_position`` (top/center/bottom)
      with 0.3s alpha fade in and out. EDL-driven; assembly_service reads
      both from edl.json per scene."""
    duration = max(0.1, scene['duration'])

    if _clip_cache_hit(
        scene, footage_path, output_path, transition, ken_burns,
        overlay_text=overlay_text,
        overlay_position=overlay_position if overlay_text else None,
    ):
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

    # Overlay text comes after fade so the text doesn't fade with the clip
    # transition (it has its own alpha ramp). drawtext renders on top of
    # whatever color the underlying frame is at that moment.
    if overlay_text:
        overlay_filter = _build_overlay_filter(
            overlay_text, overlay_position, duration,
        )
        if overlay_filter:
            filters.append(overlay_filter)

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
            "overlay_text": overlay_text,
            "overlay_position": overlay_position if overlay_text else None,
            "cache_version": _CLIP_CACHE_VERSION,
        }, f)


def _load_or_create_edl(
    project_name: str,
    *,
    transition: str,
    ken_burns: bool,
) -> dict:
    """Return the saved EDL, or auto-generate + persist one if missing.

    Auto-generation preserves the contract that a render-without-edit-first
    still works: we synthesize an EDL using the per-render transition +
    ken_burns choices so the behavior matches pre-EDL rendering for
    non-listicle videos. Listicle videos additionally get their auto-text
    overlays even on the first render."""
    edl = load_edl(project_name)
    if edl is not None:
        return edl
    print("  No edl.json found — auto-generating default EDL.")
    edl = generate_default_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    save_edl(project_name, edl)
    print(f"  edl.json saved ({len(edl['scenes'])} scenes)")
    return edl


def render_all_scene_clips(
    project_name: str,
    footage_paths: dict,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> list[str]:
    """Render every scene clip. Returns ordered list of clip paths.

    Per-scene render parameters come from edl.json (auto-generated if
    absent). The transition + ken_burns kwargs here are *defaults* passed
    into auto-generation; once an EDL exists, the EDL is authoritative."""
    windows = load_scene_windows(project_name)
    edl = _load_or_create_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    # Index EDL entries by scene id so a window list reordered upstream
    # (e.g. dropped hallucinated final scene) still pairs correctly.
    edl_by_id: dict[int, dict] = {e["id"]: e for e in edl.get("scenes", [])}

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

        entry = edl_by_id.get(sid, {})
        # Forward-compat: assembly reads only the keys it knows. Missing keys
        # fall back to the call-site defaults (so an older EDL without
        # overlay_text keys still renders cleanly).
        per_scene_transition = entry.get("transition", transition)
        per_scene_ken_burns = entry.get("ken_burns", ken_burns)
        overlay_text = entry.get("overlay_text")
        overlay_position = entry.get("overlay_position") or "top"

        if _clip_cache_hit(
            scene, src, out, per_scene_transition, per_scene_ken_burns,
            overlay_text=overlay_text,
            overlay_position=overlay_position if overlay_text else None,
        ):
            cached += 1
        else:
            print(f"  Rendering clip: scene {sid}  ({scene['duration']:.1f}s)...")
            render_scene_clip(
                scene, src, out,
                transition=per_scene_transition,
                ken_burns=per_scene_ken_burns,
                overlay_text=overlay_text,
                overlay_position=overlay_position,
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
    Both kwargs become DEFAULTS for EDL auto-generation when no edl.json
    exists yet; once an EDL is present, its per-scene values are
    authoritative and these kwargs are ignored."""
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
