import json
import os
import subprocess
from pathlib import Path

from services.channel_registry import resolve_channel_editing
from services.edl_service import (
    EDL_SCHEMA_VERSION,
    _listicle_segment_titles,
    generate_default_edl,
    is_current_version,
    load_edl,
    save_edl,
)
from services.paths import PROJECTS_ROOT
from services.scene_timing_service import load_scene_windows, load_audio_timeline
from services.subtitle_service import build_subtitles
from services.voice_service import CHUNK_GAP

FPS = 25
OUT_W, OUT_H = 1920, 1080

# Frontend dir hosting the Remotion renderer (scripts/render-remotion.mjs) used
# by render_section_card. Anchored off this file (backend/services/…) so it
# resolves regardless of the caller's cwd: parent x3 == repo root.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
RENDER_SCRIPT = FRONTEND_DIR / "scripts" / "render-remotion.mjs"

# Section-card defaults. A short Remotion title card fronts each section-intro
# scene, eating into THAT scene's own frames (never spanning into the next), so
# the assembled video length is unchanged. Hardcoded for now; the channel-preset
# + per-video graphics_config that will drive card look/duration is a follow-up.
SECTION_CARD_SECONDS = 2.5
SECTION_CARD_COMP = "GardenBand"

# Ken Burns supersample quality knobs. Defaults preserve current "final-render
# quality" behavior — every render gets the best output by default. Lower the
# values during iteration to trade quality for render speed.
#
# SUPERSAMPLE: 4 (default) = current quality (eliminates sub-pixel jitter).
#   Setting to 2 cuts spatial supersample work ~4x at the cost of some
#   residual jitter on slow-zoom shots.
# TEMPORAL_SUPERSAMPLE: 2 (default) = current motion-blur chain. Setting to 1
#   skips the tblend/framestep pair entirely (~2x faster render, motion looks
#   slightly steppier on fast pans).
RENDER_KB_SUPERSAMPLE = int(os.environ.get("RENDER_KB_SUPERSAMPLE", "4"))
RENDER_KB_TEMPORAL_SUPERSAMPLE = int(os.environ.get("RENDER_KB_TEMPORAL_SUPERSAMPLE", "2"))

# Bump when filter math changes in a way that should invalidate cached clips
# (e.g., Ken Burns formula change, fade duration change). The boolean flags
# in the cache key only catch flag flips; raw filter changes need this knob.
# v6: per-scene EDL drives overlay_text + overlay_position; cache key now
# includes both so a text change invalidates only the affected clip.
# v7: Ken Burns supersample is env-driven; bump invalidates v6 clips.
# v8: EDL v2 overlays list (header/callout/counter) with per-overlay animation
#     + drawtext expansion=none; cache key swaps overlay_text/overlay_position
#     for an overlays signature + an editing-style signature.
# v9: single-quote-safe overlay text escaping. drawtext text= is unescaped
#     twice (filtergraph split + option parse), so apostrophe breaks out with a
#     triple backslash (' -> '\\\'') and colon escapes to \: ; commas/brackets
#     stay literal (guarded by the quotes). Replaces the arg-escaper that
#     crashed on apostrophes. Re-renders any clip cached under v8.
# v10: clips rendered to exact scene['frames'], not -t seconds; key gains frames
_CLIP_CACHE_VERSION = 10

# Per-clip fade-in/out duration when transition="fade". 0.15s in + 0.15s out
# per clip keeps total video duration unchanged (audio stays in sync) and
# produces a soft dip-through-black between scenes.
FADE_DUR = 0.15

# Crossfade width (in frames) applied at each section boundary when
# section_transitions is on. 12 frames == 0.48s at 25 fps; the half-width (6,
# even) is added to BOTH clips flanking a seam so the blend is frame-exact and
# symmetric about the original cut while the blended pair still emits exactly
# Fa+Fb frames (total video length — and therefore the audio + subtitle
# timelines — stay unchanged). Distinct from FADE_DUR (per-clip dip-to-black).
SECTION_XFADE_FRAMES = 12

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


def _escape_filter_arg(s: str) -> str:
    """Escape a string for use as an ffmpeg filtergraph argument value.

    libavfilter's filtergraph parser treats backslash, single quote, colon,
    comma, square brackets, and semicolon as structural characters. Any value
    that may legitimately contain them (paths with colons or commas, text
    with quotes) must escape them or the graph fails to parse. Backslash
    MUST be escaped first so subsequent escapes don't get re-escaped."""
    s = s.replace("\\", "\\\\")
    for ch in ("'", ":", ",", "[", "]", ";"):
        s = s.replace(ch, "\\" + ch)
    return s


def _escape_drawtext(s: str) -> str:
    """Escape text for the caller's single-quoted ffmpeg drawtext text= value.

    The caller wraps the result as ``text='...'``. ffmpeg unescapes a drawtext
    ``text=`` value TWICE — once when it splits the filtergraph into filter
    args, again when the drawtext filter parses its own option string — and the
    ``-vf`` graph reaches ffmpeg as a single argv (no shell to pre-join quotes).
    Two characters need handling; everything else is safe as-is:

      * ``:`` — the option-value separator. The outer quotes are consumed by the
        first pass, so a literal colon reaches the second pass unguarded and
        must be backslash-escaped as ``\\:``. That backslash sits inside the
        outer quotes (the first pass leaves it alone) and the second pass
        consumes it, so the colon renders cleanly with no visible backslash. A
        raw ``:`` instead makes the filterchain fail to parse.
      * ``'`` — cannot sit inside single quotes, so it must break out
        (close-quote, emit the quote, reopen). Because that broken-out span is
        unescaped twice, the quote needs THREE backslashes to survive both
        passes: each ``'`` becomes the six characters ' \\ \\ \\ ' ' (see the
        replacement below). The single-backslash form a shell would use
        (``'\\''``) is fully consumed by the first pass, leaving a bare quote
        that corrupts the second pass and SILENTLY drops the whole overlay.

    ``,`` ``;`` ``[`` ``]`` stay literal — the outer quotes protect them in the
    first pass and they aren't special in the second. ``%`` renders literally
    because every overlay drawtext is emitted with ``expansion=none``; real
    overlay text never contains a backslash. Newlines/CRs collapse to spaces
    (single-line overlay is the only layout)."""
    cleaned = s.replace("\n", " ").replace("\r", " ")
    cleaned = cleaned.replace("'", "'" + "\\" * 3 + "''")  # ' -> '\\\''
    cleaned = cleaned.replace(":", "\\:")
    return cleaned


def _overlay_position_expr(position: str, *, margin: int = 40) -> tuple[str, str]:
    """Return (x_expr, y_expr) for drawtext given a position keyword.
    Defaults to top for unknown values rather than raising — overlays are
    cosmetic, a bad position string shouldn't kill the render.

    ``upper_third`` (y=h/3) and ``top_right`` (y=margin, right-aligned) both
    clear the bottom karaoke-subtitle band (subtitle_service ALIGNMENT=2 bottom
    centre, MARGIN_V=110, always on) so a callout/counter never collides with
    the burned-in subtitles; ``top_right`` also clears a ``top`` header."""
    if position == "center":
        return "(w-text_w)/2", "(h-text_h)/2"
    if position == "bottom":
        return "(w-text_w)/2", "h*7/8-text_h"
    if position == "upper_third":
        return "(w-text_w)/2", "h/3"
    if position == "top_right":
        return f"w-text_w-{margin}", f"{margin}"
    # "top" (and fallback)
    return "(w-text_w)/2", "h/8"


def _fade_alpha_expr(duration: float, fade_in: float, fade_out: float) -> str:
    """drawtext alpha ramp over a whole-scene overlay: fade in over ``fade_in``
    s, hold at full opacity, fade out over ``fade_out`` s. A window too short to
    hold (duration <= fade_in + fade_out) collapses to a symmetric up-then-down
    ramp so tiny scenes never flash full opacity or hold a negative window."""
    if duration <= fade_in + fade_out:
        half = max(1e-3, duration / 2)
        return (
            f"if(lt(t,{half:.3f}),t/{half:.3f},"
            f"({duration:.3f}-t)/{half:.3f})"
        )
    out_start = duration - fade_out
    return (
        f"if(lt(t,{fade_in:.3f}),t/{fade_in:.3f},"
        f"if(lt(t,{out_start:.3f}),1,"
        f"({duration:.3f}-t)/{fade_out:.3f}))"
    )


def _build_overlay_drawtext(
    overlay: dict,
    kind_style: dict,
    scene_duration: float,
) -> str | None:
    """Build one drawtext filter for a single overlay dict, or None if no font
    is available (logged once per render) or the overlay window collapses.

    ``overlay`` carries the per-scene decision baked into the EDL at generation
    time (kind / text / position / animation / start_offset / duration);
    ``kind_style`` is that kind's slice of the resolved channel editing style
    and carries the *look* (fontsize / box_opacity / box_border / margin) plus
    the animation timings (entrance / exit_fade / slide_distance / settle).

    Every drawtext is emitted with ``expansion=none`` so a literal ``%`` in the
    text renders as ``%`` instead of triggering drawtext's ``%{...}`` expansion
    (the prior blackout bug). expansion=none does not affect the x / y / alpha /
    enable expression evaluation. Expression values that contain commas are
    single-quoted so the top-level comma that joins filters isn't misparsed."""
    font = _overlay_font_path()
    if font is None:
        print(
            "  WARN: no overlay font found on this system; skipping text "
            f"overlay {overlay.get('text')!r}. Tried: {_OVERLAY_FONT_CANDIDATES}"
        )
        return None

    text_esc = _escape_drawtext(overlay.get("text") or "")
    position = overlay.get("position") or "top"
    animation = overlay.get("animation") or "none"
    margin = int(kind_style.get("margin", 40))
    x_expr, base_y = _overlay_position_expr(position, margin=margin)

    fontsize = int(kind_style.get("fontsize", 64))
    box_opacity = float(kind_style.get("box_opacity", 0.6))
    box_border = int(kind_style.get("box_border", 20))

    start_offset = float(overlay.get("start_offset") or 0.0)
    raw_duration = overlay.get("duration")
    end = scene_duration if raw_duration is None else min(
        start_offset + float(raw_duration), scene_duration
    )

    enable_expr: str | None = None
    if animation == "slide_up":
        # Header: eases up into place over `entrance`, fading in/out across the
        # whole scene. y travels base_y+slide -> base_y.
        entrance = float(kind_style.get("entrance", 0.4))
        exit_fade = float(kind_style.get("exit_fade", 0.3))
        slide = float(kind_style.get("slide_distance", 40))
        y_expr = f"({base_y})+{slide:.3f}*(1-min(1,t/{max(1e-3, entrance):.3f}))"
        alpha_expr = _fade_alpha_expr(scene_duration, entrance, exit_fade)
    elif animation == "pop":
        # Callout: visible for [start_offset, end]; pops up 12px and settles
        # over `settle`, with a quick 0.12s fade-in / 0.2s fade-out.
        if end <= start_offset:
            return None  # window collapsed to nothing on a very short scene
        settle = float(kind_style.get("settle", 0.15))
        o, en = start_offset, end
        window = en - o
        enable_expr = f"between(t,{o:.3f},{en:.3f})"
        y_expr = (
            f"({base_y})-12*(1-min(1,max(0,(t-{o:.3f}))/{max(1e-3, settle):.3f}))"
        )
        fade_in, fade_out = 0.12, 0.2
        if window <= fade_in + fade_out:
            half = max(1e-3, window / 2)
            mid = o + half
            alpha_expr = (
                f"if(lt(t,{mid:.3f}),(t-{o:.3f})/{half:.3f},"
                f"({en:.3f}-t)/{half:.3f})"
            )
        else:
            hold_end = en - fade_out
            alpha_expr = (
                f"if(lt(t,{o + fade_in:.3f}),(t-{o:.3f})/{fade_in:.3f},"
                f"if(lt(t,{hold_end:.3f}),1,"
                f"({en:.3f}-t)/{fade_out:.3f}))"
            )
    elif animation == "fade":
        # Header fallback: fade in/out, no slide.
        entrance = float(kind_style.get("entrance", 0.4))
        exit_fade = float(kind_style.get("exit_fade", 0.3))
        y_expr = base_y
        alpha_expr = _fade_alpha_expr(scene_duration, entrance, exit_fade)
    else:
        # "none" / static (counter, or any unknown animation): fixed position,
        # brief 0.2s fade-in then hold for the rest of the scene.
        y_expr = base_y
        alpha_expr = "if(lt(t,0.2),t/0.2,1)"

    parts = [
        f"text='{text_esc}'",
        f"fontfile='{_escape_filter_arg(font)}'",
        "expansion=none",
        f"fontsize={fontsize}",
        "fontcolor=white",
        "box=1",
        f"boxcolor=black@{box_opacity:g}",
        f"boxborderw={box_border}",
        f"x='{x_expr}'",
        f"y='{y_expr}'",
        f"alpha='{alpha_expr}'",
    ]
    if enable_expr is not None:
        parts.append(f"enable='{enable_expr}'")
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
    audio_dir = str(PROJECTS_ROOT / project_name / "audio")
    video_dir = str(PROJECTS_ROOT / project_name / "video")
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
    # Prefix is shared by both loudnorm passes: chunk filters + concat to
    # produce a single [concat] label. Each pass appends its own loudnorm
    # tail to this prefix.
    filter_prefix = (
        ";".join(chunk_filters)
        + ";"
        + f"{''.join(concat_labels)}concat=n={n_segments}:v=0:a=1[concat]"
    )

    out_path = os.path.join(video_dir, "full_audio.mp3")
    # Two-pass loudnorm on [concat]:
    #   pass 1 — measurement: loudnorm=...:print_format=json with -f null -
    #     writes program-wide integrated loudness / true peak / LRA / threshold
    #     / offset to stderr as a JSON block. No audio is written.
    #   pass 2 — apply: loudnorm with linear=true and the measured_* values
    #     from pass 1, which makes loudnorm perform a single linear gain
    #     adjustment over the whole file instead of dynamic per-window gain
    #     riding. The dynamic mode (what a single-pass invocation does) was
    #     the source of audible breathing/pumping on speech in the previous
    #     chain — linear=true requires measured_* inputs and is only valid in
    #     two-pass mode. TP=-2 is now firm: with linear gain there's no
    #     window-by-window overshoot to worry about, so -2 dBFS headroom is
    #     enough to guarantee no true-peak clipping without an alimiter.
    #
    # Parse failure is loud by design — a malformed/missing JSON block means
    # ffmpeg changed its output format or the chunk filters errored before
    # loudnorm ran; either way we'd rather raise than silently fall back to
    # the pumpy single-pass behavior we just removed.
    #
    # MP3 bitrate bumped to 192k (libmp3lame default trends ~128k VBR);
    # ElevenLabs source is mp3_44100_192, matching this re-encode bitrate
    # so we don't compound compression artifacts.
    measure_filter = (
        filter_prefix
        + ";[concat]loudnorm=I=-16:TP=-2:LRA=11:print_format=json[out]"
    )
    measure_cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", measure_filter,
        "-map", "[out]",
        "-f", "null", "-",
    ]
    try:
        measure_proc = subprocess.run(measure_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(f"ffmpeg failed loudnorm measurement pass for {project_name}:\n{stderr}")
        raise

    measure_stderr = measure_proc.stderr.decode("utf-8", errors="replace")
    # Parse the LAST {...} block in stderr — ffmpeg emits the loudnorm summary
    # near the end after the per-frame progress lines.
    last_open = measure_stderr.rfind("{")
    last_close = measure_stderr.rfind("}")
    if last_open == -1 or last_close == -1 or last_close < last_open:
        tail = measure_stderr[-2000:]
        raise RuntimeError(
            "loudnorm measurement pass produced no JSON block in stderr. "
            f"Last 2000 chars of stderr:\n{tail}"
        )
    try:
        measured = json.loads(measure_stderr[last_open:last_close + 1])
    except json.JSONDecodeError as e:
        tail = measure_stderr[-2000:]
        raise RuntimeError(
            f"loudnorm measurement JSON failed to parse ({e}). "
            f"Last 2000 chars of stderr:\n{tail}"
        )

    required_keys = (
        "input_i", "input_tp", "input_lra", "input_thresh", "target_offset",
    )
    missing_keys = [k for k in required_keys if k not in measured]
    if missing_keys:
        tail = measure_stderr[-2000:]
        raise RuntimeError(
            f"loudnorm measurement JSON missing keys {missing_keys}. "
            f"Parsed: {measured!r}. Last 2000 chars of stderr:\n{tail}"
        )

    apply_filter = (
        filter_prefix
        + ";[concat]loudnorm=I=-16:TP=-2:LRA=11:linear=true"
        + f":measured_I={measured['input_i']}"
        + f":measured_TP={measured['input_tp']}"
        + f":measured_LRA={measured['input_lra']}"
        + f":measured_thresh={measured['input_thresh']}"
        + f":offset={measured['target_offset']}[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", apply_filter,
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


def _overlays_signature(overlays: list[dict] | None) -> str:
    """Stable JSON signature of a scene's overlays list for the clip cache key.
    sort_keys makes it insensitive to dict key ordering; the list order is
    deterministic from generate_default_edl."""
    return json.dumps(overlays or [], sort_keys=True)


def _edit_style_signature(edit_style: dict | None) -> str:
    """Stable JSON signature of the resolved channel editing style so a style
    change (fontsize / box / animation timings) re-renders the affected clips
    even when the overlays list itself is unchanged."""
    return json.dumps(edit_style or {}, sort_keys=True)


def _scene_frame_count(scene: dict) -> int:
    """Exact number of frames this scene's clip must render to.

    scene_timing_service frame-quantizes the whole narration timeline and
    stamps each scene with an integer ``frames``; that count is authoritative
    so concatenated clip frames sum to the quantized total (== audio length)
    with no per-scene drift. The render encodes exactly this many frames and
    derives its duration clock from it, and the clip cache keys on it. The
    fallback reconstructs a count from ``duration`` for older
    scene_windows.json written before the ``frames`` field existed."""
    frames = scene.get("frames")
    if frames is None:
        frames = max(1, round(max(0.1, scene["duration"]) * FPS))
    return int(frames)


def _clip_cache_hit(
    scene: dict,
    footage_path: str,
    output_path: str,
    transition: str,
    ken_burns: bool,
    overlays: list[dict] | None = None,
    edit_style: dict | None = None,
) -> bool:
    """True iff a previously-rendered clip is still valid for these inputs.

    The overlays signature + editing-style signature are part of the key so an
    EDL overlay change (text / position / animation) OR a channel style change
    (fontsize / box / animation timings) invalidates only the affected
    scene(s), not the whole project's clip cache."""
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
        and cache.get("frames") == _scene_frame_count(scene)
        and cache.get("out_w") == OUT_W
        and cache.get("out_h") == OUT_H
        and cache.get("fps") == FPS
        and cache.get("transition") == transition
        and cache.get("ken_burns") == ken_burns
        and cache.get("overlays_sig") == _overlays_signature(overlays)
        and cache.get("edit_style_sig") == _edit_style_signature(edit_style)
        and cache.get("cache_version") == _CLIP_CACHE_VERSION
    )


def render_scene_clip(
    scene: dict,
    footage_path: str,
    output_path: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
    overlays: list[dict] | None = None,
    edit_style: dict | None = None,
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

    overlays: zero or more EDL overlay dicts (kind / text / position /
      animation / start_offset / duration) drawn as drawtext filters composited
      over the final frame, in list order, after scale/crop/Ken Burns/fade so
      they're never zoomed or cropped. edit_style is the resolved channel
      editing style supplying each kind's look (fontsize / box / animation
      timings). Both are read from edl.json + resolve_channel_editing per
      scene by render_all_scene_clips."""
    # Frame count is the single source of truth for this clip's length. The
    # timeline was frame-quantized upstream, so we encode exactly this many
    # frames and derive the duration clock from it — every filter (Ken Burns,
    # fade, overlays) and the encode then share one clock, and the concatenated
    # clips sum to the quantized total (== audio length).
    frames = _scene_frame_count(scene)
    duration = frames / FPS

    if _clip_cache_hit(
        scene, footage_path, output_path, transition, ken_burns,
        overlays=overlays, edit_style=edit_style,
    ):
        return  # cache hit — output already valid

    is_png = str(footage_path).lower().endswith(".png")

    # Standard chain when Ken Burns is OFF (or source is video).
    # When Ken Burns is ON and source is a PNG, swap zoompan entirely
    # for a scale-with-eval=frame + center-crop + motion-blur chain.
    # zoompan's per-frame integer rounding of the crop center was the
    # root cause of the residual jitter (visible 1px jumps every few
    # frames); the `scale=eval=frame` filter does subpixel-accurate
    # interpolation per frame instead. tblend at 2x temporal sampling
    # smooths whatever rounding remains in the center-crop stage.
    if ken_burns and is_png:
        # Spatial + temporal supersample knobs are env-driven (see module
        # constants). Defaults match the prior hardcoded 4x / 2x behavior so
        # final renders are unchanged; lower the env vars for fast iteration.
        SUPER = RENDER_KB_SUPERSAMPLE
        FPS_HI = FPS * RENDER_KB_TEMPORAL_SUPERSAMPLE
        sw, sh = OUT_W * SUPER, OUT_H * SUPER
        # Exact (not ceil'd): duration == frames/FPS and FPS_HI ==
        # FPS*SUPERSAMPLE, so this is precisely duration*FPS_HI with no
        # fractional-frame slop. After tblend+framestep (÷SUPERSAMPLE) the
        # chain emits exactly `frames`, matching the -frames:v cap below so the
        # zoom completes on the last rendered frame.
        total_frames_hi = frames * RENDER_KB_TEMPORAL_SUPERSAMPLE
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
        ]
        if RENDER_KB_TEMPORAL_SUPERSAMPLE > 1:
            # Pair of frames -> averaged blend -> drop every other to land
            # back at FPS. Only valid when FPS_HI > FPS; when temporal
            # supersample is 1, FPS_HI == FPS already so we skip both.
            filters.append("tblend=all_mode=average")
            filters.append("framestep=2")
        filters.append(f"scale={OUT_W}:{OUT_H}:flags=lanczos")
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

    # Overlays come after fade so their own alpha ramps aren't multiplied by
    # the clip fade, and after scale/crop/Ken Burns so they compose over the
    # final 1920x1080 canvas (never zoomed or cropped). Chained in list order;
    # drawtext renders on top of whatever colour the frame is at that moment.
    for overlay in (overlays or []):
        kind_style = (edit_style or {}).get(overlay.get("kind")) or {}
        overlay_filter = _build_overlay_drawtext(overlay, kind_style, duration)
        if overlay_filter:
            filters.append(overlay_filter)

    vf = ",".join(filters)

    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", footage_path,
        "-vf", vf,
        "-frames:v", str(frames),
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
            "frames": frames,
            "out_w": OUT_W,
            "out_h": OUT_H,
            "fps": FPS,
            "transition": transition,
            "ken_burns": ken_burns,
            "overlays_sig": _overlays_signature(overlays),
            "edit_style_sig": _edit_style_signature(edit_style),
            "cache_version": _CLIP_CACHE_VERSION,
        }, f)


def render_extended_clip(
    scene: dict,
    footage_path: str,
    out: str,
    *,
    extra_frames: int,
    transition: str = "cut",
    ken_burns: bool = False,
    overlays: list[dict] | None = None,
    edit_style: dict | None = None,
) -> str:
    """Render one scene clip lengthened by ``extra_frames`` for a section
    crossfade, to a DISTINCT ``scene_{id}.xfade.mp4`` (its own cache sidecar; the
    plain ``scene_{id}.mp4`` and its cache are left untouched).

    The two clips flanking a section boundary are each rendered +half-a-crossfade
    frames so concat_clips_crossfade's ``xfade`` can blend across the seam and
    still emit exactly Fa+Fb frames. Delegates to render_scene_clip with a
    frame-bumped scene, so Ken Burns / fade / overlays all animate over the
    extended clock (the accepted trade-off: a B-side header animates on the
    +6-frame clip). ``duration`` is updated alongside ``frames`` because
    render_scene_clip's cache-hit check reads scene['duration']; leaving it stale
    would spuriously miss the cache on every rerun."""
    frames = _scene_frame_count(scene) + extra_frames
    ext_scene = {**scene, "frames": frames, "duration": round(frames / FPS, 3)}
    render_scene_clip(
        ext_scene, footage_path, out,
        transition=transition, ken_burns=ken_burns,
        overlays=overlays, edit_style=edit_style,
    )
    return out


# ---------------------------------------------------------------------------
# Section cards (zero-added-time title cards fronting each section-intro scene)
#
# For the first scene of each body segment we render a Remotion title card and
# concatenate it with a SHORTENED footage segment so card_frames + footage_frames
# == the scene's own frame count EXACTLY. The card thus eats into the scene's
# frames (never adds any), so the total video length — and therefore the audio
# and subtitle timelines — is untouched. Output goes to a distinct
# ``scene_{sid:03d}.card.mp4`` path; the plain clip + its cache stay intact so a
# card-off render is unaffected.
# ---------------------------------------------------------------------------

def _normalize_video_chain() -> str:
    """The per-input normalization applied to EVERY concat-filter input (scene
    clips AND card MP4s) before it reaches the concat/xfade filters.

    Fit-to-fill 1920x1080, constant 25 fps, yuv420p, square pixels. The concat
    filter demands identical width/height/SAR/format/fps across inputs; card
    MP4s render at 30 fps from Remotion and clips are already 25 fps CFR, so
    forcing one shape here is what lets the two interleave. Applied to clips too
    (not just cards) so a single code path guarantees the match."""
    return (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},fps={FPS},format=yuv420p,setsar=1"
    )


def render_section_card(
    index: str,
    title: str,
    out_path: str,
    *,
    duration: float = SECTION_CARD_SECONDS,
    comp: str = SECTION_CARD_COMP,
) -> str:
    """Render one Remotion section-header card to a silent MP4 at ``out_path``.

    Reuses the SAME renderer the /remotion tab drives (frontend
    scripts/render-remotion.mjs) via subprocess, cwd=<frontend>. A COMPLETE prop
    set is passed (index + title + the garden defaults) so nothing falls back to
    the designer's demo props; ``subtitle`` is explicitly blanked so the card
    shows only the numbered section title. The raw card renders at the comp's
    native 30 fps; _normalize_card_to_clip resamples it to the canonical
    25 fps / 1920x1080 / yuv420p / SAR 1:1 shape and caps it to exact frames."""
    props = {
        "index": str(index),
        "title": title,
        "subtitle": "",  # title-only card (blank the designer demo subtitle)
        "durationInSeconds": float(duration),
        "animation": "rise",
        "palette": {"background": "#e9f1e4", "text": "#2f4a34", "accent": "#7bae5a"},
        "background": "gradient",
        "decoration": {"set": "leaves", "density": "low"},
        "fontFamily": "nunito",
    }
    cmd = [
        "node", str(RENDER_SCRIPT),
        f"--comp={comp}",
        f"--props={json.dumps(props)}",
        f"--out={out_path}",
    ]
    try:
        subprocess.run(cmd, cwd=str(FRONTEND_DIR), check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        print(f"Remotion card render failed for {title!r}:\n{stdout}\n{stderr}")
        raise
    return out_path


def _normalize_card_to_clip(raw_path: str, frames: int, out_path: str) -> str:
    """Re-encode a raw Remotion card MP4 to the canonical scene-clip shape and
    cap it to exactly ``frames`` frames.

    ``_normalize_video_chain`` fits it to 1920x1080 / 25 fps / yuv420p / SAR 1:1
    (matching every plain scene clip so the concat demuxer can stream-copy the
    seam), and ``-frames:v frames`` trims it to the card's frame budget. The raw
    card is >= this many frames (2.5 s at 25 fps == 62.5 frames >= 62), so the
    cap only ever drops the tail.

    The extra ``scale=in_range=pc:out_range=tv`` after the shared chain converts
    the card from full-range (Remotion renders yuvj420p / color_range=pc) to the
    limited-range yuv420p / color_range=tv that every stock-footage scene clip
    already carries. Without it the card stays yuvj420p and the top-level concat
    demuxer would refuse to stream-copy the mismatched seam (and the card's
    colors would read a touch off against the tv-range footage). The card is the
    ONLY full-range source, so this conversion lives here rather than in the
    shared chain (kept verbatim)."""
    vf = _normalize_video_chain() + ",scale=in_range=pc:out_range=tv"
    subprocess.run([
        "ffmpeg", "-y", "-i", os.path.abspath(raw_path),
        "-vf", vf,
        "-frames:v", str(frames),
        "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        os.path.abspath(out_path),
    ], check=True, capture_output=True)
    return out_path


def _concat_segments_copy(segs: list[str], output_path: str, base: str) -> str:
    """Join already-canonical segments with the concat demuxer (stream copy).

    Both the card segment and the footage segment are encoded to the identical
    canonical shape (1920x1080 / 25 fps / yuv420p tv-range / SAR 1:1 / tb
    1/12800), so a stream copy preserves every frame with no re-encode. If the
    demuxer ever refuses the seam, fall back to a concat-filter re-encode of just
    this 2-segment join (re-normalizing each input) and note it."""
    concat_txt = base + ".concat.txt"
    with open(concat_txt, "w") as f:
        for p in segs:
            f.write(f"file '{os.path.abspath(p)}'\n")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-c", "copy", os.path.abspath(output_path),
        ], check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(
            "  Section-card seam rejected by concat demuxer copy "
            f"({stderr[-400:].strip()!r}); falling back to concat-filter "
            "re-encode of the 2-segment join."
        )

    input_args: list[str] = []
    for p in segs:
        input_args += ["-i", os.path.abspath(p)]
    norm = _normalize_video_chain()
    n = len(segs)
    graph = (
        ";".join(f"[{i}:v]{norm}[n{i}]" for i in range(n)) + ";"
        + "".join(f"[n{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    )
    subprocess.run([
        "ffmpeg", "-y", *input_args,
        "-filter_complex", graph, "-map", "[outv]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        os.path.abspath(output_path),
    ], check=True, capture_output=True)
    return output_path


def render_section_intro_clip(
    scene: dict,
    footage_path: str,
    output_path: str,
    *,
    index: str,
    title: str,
    card_seconds: float = SECTION_CARD_SECONDS,
    card_comp: str = SECTION_CARD_COMP,
    transition: str = "cut",
    ken_burns: bool = False,
    overlays: list[dict] | None = None,
    edit_style: dict | None = None,
) -> str:
    """Render a section-intro scene as ``[card | card_frames] ++ [footage |
    footage_frames]`` where ``card_frames + footage_frames == scene['frames']``
    EXACTLY, written to ``output_path`` (``scene_{sid:03d}.card.mp4``).

    ``card_frames = min(round(card_seconds * FPS), scene_frames)``: the card eats
    into the scene's own frames and NEVER spans into the next scene, so the total
    video length is unchanged. On the clamp (scene_frames <= card_frames) the
    card fills the whole scene and there is no footage segment. The footage
    segment renders through the normal render_scene_clip path (Ken Burns / fade /
    any remaining overlays apply) at the shortened frame count, with the header +
    counter overlays already stripped by the caller — the card now carries the
    section number (its badge) + the title. The card hard-cuts into the footage;
    the scene's own transition is passed to the footage segment."""
    scene_frames = _scene_frame_count(scene)
    card_frames = min(round(card_seconds * FPS), scene_frames)
    footage_frames = scene_frames - card_frames

    base = os.path.splitext(output_path)[0]  # …/scene_013.card
    raw_card = base + ".raw.mp4"
    card_seg = base + ".cardseg.mp4"
    foot_seg = base + ".footseg.mp4"

    render_section_card(index, title, raw_card, duration=card_seconds, comp=card_comp)
    _normalize_card_to_clip(raw_card, card_frames, card_seg)

    segs = [card_seg]
    if footage_frames > 0:
        render_scene_clip(
            {**scene, "frames": footage_frames}, footage_path, foot_seg,
            transition=transition, ken_burns=ken_burns,
            overlays=overlays, edit_style=edit_style,
        )
        segs.append(foot_seg)

    _concat_segments_copy(segs, output_path, base)
    return output_path


def derive_section_cards(project_name: str) -> dict[int, dict]:
    """Map ``scene_id -> {"index": str, "title": str}`` for the FIRST scene of
    each body segment (``segment_id >= 0``) — the section-intro scenes that get a
    card.

    Titles come from script_draft.json's segment list via the SAME
    ``_listicle_segment_titles`` logic the EDL header text uses; when
    script_draft is absent/unreadable we fall back to each window's own
    ``segment_title``. ``index`` is the 1-based segment number
    (``segment_id + 1``), matching the EDL's ``"{N}. {title}"`` header. A segment
    with no resolvable title yields no card (skipped)."""
    windows = load_scene_windows(project_name)
    seg_titles: dict[int, str] = {}
    draft_path = PROJECTS_ROOT / project_name / "script_draft.json"
    if draft_path.exists():
        try:
            with draft_path.open() as f:
                draft = json.load(f)
            seg_titles = _listicle_segment_titles(draft.get("segments", []))
        except (OSError, json.JSONDecodeError):
            seg_titles = {}

    cards: dict[int, dict] = {}
    seen: set[int] = set()
    for s in windows:
        seg = s.get("segment_id")
        if seg is None or seg < 0 or seg in seen:
            continue
        seen.add(seg)
        title = seg_titles.get(seg) or (s.get("segment_title") or "").strip()
        if not title:
            continue
        cards[s["id"]] = {"index": str(seg + 1), "title": title}
    return cards


def _project_channel_id(project_name: str) -> str | None:
    """Read the project's channel from script_config.json — the same source
    edl_service uses to resolve the editing style, so the render layer resolves
    the *same* style the EDL's overlay positions/animations were baked from.
    Returns None (→ default channel downstream) when the config or key is
    absent."""
    p = PROJECTS_ROOT / project_name / "script_config.json"
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return (json.load(f) or {}).get("channel")
    except (OSError, json.JSONDecodeError):
        return None


def _load_or_create_edl(
    project_name: str,
    *,
    transition: str,
    ken_burns: bool,
) -> dict:
    """Return the saved EDL, or auto-generate + persist one if missing OR at a
    stale schema version.

    Auto-generation preserves the contract that a render-without-edit-first
    still works: we synthesize an EDL using the per-render transition +
    ken_burns choices so the behavior matches pre-EDL rendering for
    non-listicle videos. Listicle videos additionally get their auto-text
    overlays even on the first render. A version mismatch is regenerated
    deterministically (there is no manual EDL editor — api/routes/edit.py is
    read-only), reproducing all prior data while upgrading to the current
    overlays-list schema."""
    edl = load_edl(project_name)
    if edl is not None and is_current_version(edl):
        return edl
    if edl is None:
        print("  No edl.json found — auto-generating default EDL.")
    else:
        print(
            f"  edl.json is schema v{edl.get('version')} (current is "
            f"v{EDL_SCHEMA_VERSION}) — regenerating."
        )
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
    section_cards: dict | None = None,
    card_seconds: float = SECTION_CARD_SECONDS,
    card_comp: str = SECTION_CARD_COMP,
) -> list[str]:
    """Render every scene clip. Returns ordered list of clip paths.

    Per-scene render parameters come from edl.json (auto-generated if
    absent). The transition + ken_burns kwargs here are *defaults* passed
    into auto-generation; once an EDL exists, the EDL is authoritative.

    ``section_cards`` (optional): ``{scene_id: {"index", "title"}}`` from
    derive_section_cards. Each listed scene is rendered as a title card fronting a
    shortened footage segment (render_section_intro_clip → scene_{sid}.card.mp4)
    instead of a plain clip, and that ``.card.mp4`` path is returned in its slot
    so the downstream concat picks it up. ``None`` (default) renders every scene
    the plain way — byte-identical to the pre-card path. ``card_seconds`` /
    ``card_comp`` set the card length + Remotion comp."""
    windows = load_scene_windows(project_name)
    edl = _load_or_create_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    # Index EDL entries by scene id so a window list reordered upstream
    # (e.g. dropped hallucinated final scene) still pairs correctly.
    edl_by_id: dict[int, dict] = {e["id"]: e for e in edl.get("scenes", [])}

    # Resolve the channel's on-screen editing style ONCE — supplies each
    # overlay kind's look (fontsize / box / animation timings). Positions +
    # animations were already baked into the EDL at generation time from this
    # same style; this re-resolves the same channel so they stay consistent.
    edit_style = resolve_channel_editing(_project_channel_id(project_name))

    clips_dir = str(PROJECTS_ROOT / project_name / "clips")
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
        # fall back to the call-site defaults (so an EDL entry without an
        # overlays list still renders cleanly).
        per_scene_transition = entry.get("transition", transition)
        per_scene_ken_burns = entry.get("ken_burns", ken_burns)
        overlays = entry.get("overlays", [])

        # Section-intro scene → render a title card fronting a shortened footage
        # segment (zero added time) to scene_{sid}.card.mp4. The card carries the
        # section number (badge) + title, so header + counter overlays are dropped
        # from the footage segment; any other overlay (e.g. a callout) is kept.
        # The plain scene_{sid}.mp4 + its cache are left untouched.
        card = (section_cards or {}).get(sid)
        if card:
            out_card = os.path.join(clips_dir, f"scene_{sid:03d}.card.mp4")
            footage_overlays = [
                o for o in overlays if o.get("kind") not in ("header", "counter")
            ]
            print(
                f"  Rendering section card + clip: scene {sid} "
                f"({card['index']}. {card['title']})..."
            )
            render_section_intro_clip(
                scene, src, out_card,
                index=card["index"], title=card["title"],
                card_seconds=card_seconds, card_comp=card_comp,
                transition=per_scene_transition, ken_burns=per_scene_ken_burns,
                overlays=footage_overlays, edit_style=edit_style,
            )
            rendered += 1
            clip_paths.append(out_card)
            continue

        if _clip_cache_hit(
            scene, src, out, per_scene_transition, per_scene_ken_burns,
            overlays=overlays, edit_style=edit_style,
        ):
            cached += 1
        else:
            print(f"  Rendering clip: scene {sid}  ({scene['duration']:.1f}s)...")
            render_scene_clip(
                scene, src, out,
                transition=per_scene_transition,
                ken_burns=per_scene_ken_burns,
                overlays=overlays,
                edit_style=edit_style,
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
    video_dir = str(PROJECTS_ROOT / project_name / "video")
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


def _section_boundary_seams(windows: list[dict]) -> list[int]:
    """Left indices ``i`` where ``windows[i]`` and ``windows[i+1]`` sit in
    different sections (their ``segment_id`` differs) — the seams that get a
    crossfade. Covers every section change, including hook->body0 and
    body_last->conclusion (the sentinel segment_ids -1 / -2 differ from the body
    ids, so those edges are seams too).

    Raises NotImplementedError if two seams are adjacent (consecutive left
    indices differ by 1), i.e. a section is a single scene: that clip would have
    to be extended for two crossfades at once, which this step does not support
    (the <2-scene-section / card-handoff case is a later step)."""
    seams = [
        i for i in range(len(windows) - 1)
        if windows[i].get("segment_id") != windows[i + 1].get("segment_id")
    ]
    for a, b in zip(seams, seams[1:]):
        if b - a == 1:
            raise NotImplementedError(
                f"Adjacent section boundaries at clip indices {a} and {b} "
                f"(a single-scene section): that clip would participate in two "
                f"crossfades at once, which section transitions do not support."
            )
    return seams


def concat_clips_crossfade(
    project_name: str,
    clip_paths: list[str],
    footage_paths: dict,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> str:
    """Join scene clips, blending a short crossfade at each section boundary.

    A section boundary is a segment_id change between adjacent scenes
    (_section_boundary_seams). At each seam the two flanking clips are
    re-rendered +SECTION_XFADE_FRAMES//2 frames (render_extended_clip ->
    scene_{id}.xfade.mp4) and joined with an ``xfade`` centered on the ORIGINAL
    cut; every other clip passes through untouched. Because each blended pair
    still emits exactly Fa+Fb frames, the assembled length — and therefore the
    audio + subtitle timelines — are unchanged.

    Unlike concat_clips (concat demuxer, stream copy) this re-encodes: the xfade
    filter can't run on the demuxer, so every input is normalized via the shared
    _normalize_video_chain and the whole thing runs through one concat FILTER
    graph. With no seams it delegates to concat_clips. Writes the same
    video/video_no_audio.mp4 sink as concat_clips (so the downstream mux is
    unchanged) and returns its path."""
    windows = load_scene_windows(project_name)
    seams = _section_boundary_seams(windows)
    if not seams:
        # No section boundaries (e.g. a single-segment project) — nothing to
        # crossfade; fall back to the plain demuxer concat.
        return concat_clips(project_name, clip_paths)

    if len(clip_paths) != len(windows):
        raise ValueError(
            f"clip_paths ({len(clip_paths)}) and scene windows ({len(windows)}) "
            f"length mismatch — cannot align section-crossfade seams."
        )

    # Resolve per-scene render params exactly as render_all_scene_clips does so
    # each extended seam clip matches its plain counterpart (bar the +frames).
    edl = _load_or_create_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    edl_by_id: dict[int, dict] = {e["id"]: e for e in edl.get("scenes", [])}
    edit_style = resolve_channel_editing(_project_channel_id(project_name))

    clips_dir = str(PROJECTS_ROOT / project_name / "clips")
    half = SECTION_XFADE_FRAMES // 2

    # Render the two extended clips flanking each seam, override those two input
    # slots with the .xfade.mp4 paths, and record the xfade offset: the blend
    # starts at (Fa - half)/FPS into clip A (A's original frame count is Fa) so
    # its centre lands on the original cut at frame Fa.
    input_paths = list(clip_paths)
    seam_offsets: dict[int, float] = {}
    for i in seams:
        for j in (i, i + 1):
            scene = windows[j]
            sid = scene["id"]
            src = footage_paths.get(sid)
            if not src or not os.path.exists(src):
                raise FileNotFoundError(f"No footage for scene {sid}")
            entry = edl_by_id.get(sid, {})
            out = os.path.join(clips_dir, f"scene_{sid:03d}.xfade.mp4")
            render_extended_clip(
                scene, src, out,
                extra_frames=half,
                transition=entry.get("transition", transition),
                ken_burns=entry.get("ken_burns", ken_burns),
                overlays=entry.get("overlays", []),
                edit_style=edit_style,
            )
            input_paths[j] = out
        fa = _scene_frame_count(windows[i])
        seam_offsets[i] = (fa - half) / FPS

    # Build the concat FILTER graph: normalize every input (the EXISTING shared
    # chain), xfade each seam pair, concat the resulting streams. n_concat =
    # n_inputs - len(seams) because each seam merges two inputs into one stream.
    norm = _normalize_video_chain()
    n = len(input_paths)
    lines = [f"[{k}:v]{norm}[n{k}]" for k in range(n)]
    xfade_dur = SECTION_XFADE_FRAMES / FPS
    seam_set = set(seams)
    concat_labels: list[str] = []
    k = 0
    while k < n:
        if k in seam_set:
            lines.append(
                f"[n{k}][n{k + 1}]xfade=transition=fade:"
                f"duration={xfade_dur:.3f}:offset={seam_offsets[k]:.3f}[x{k}]"
            )
            concat_labels.append(f"[x{k}]")
            k += 2
        else:
            concat_labels.append(f"[n{k}]")
            k += 1
    n_concat = len(concat_labels)
    graph = (
        ";".join(lines) + ";"
        + "".join(concat_labels) + f"concat=n={n_concat}:v=1:a=0[outv]"
    )

    input_args: list[str] = []
    for p in input_paths:
        input_args += ["-i", os.path.abspath(p)]

    video_dir = str(PROJECTS_ROOT / project_name / "video")
    os.makedirs(video_dir, exist_ok=True)
    silent_video = os.path.join(video_dir, "video_no_audio.mp4")
    try:
        subprocess.run([
            "ffmpeg", "-y", *input_args,
            "-filter_complex", graph,
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            os.path.abspath(silent_video),
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(
            f"ffmpeg failed section-crossfade concat for {project_name}:\n{stderr}"
        )
        raise

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
    out = str(PROJECTS_ROOT / project_name / "video" / output_name)

    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path]
    if subtitle_path:
        # ffmpeg's subtitles filter parses the path through libavfilter syntax;
        # using an absolute path avoids confusion with the cwd at filter time.
        abs_sub = os.path.abspath(subtitle_path)
        cmd += [
            "-vf", f"subtitles='{_escape_filter_arg(abs_sub)}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        ]
    else:
        cmd += ["-c:v", "copy"]
    cmd += [
        "-map", "0:v", "-map", "1:a",
        # Pad the audio with trailing silence so it's always >= the (finite)
        # video length. -shortest then keys on the video and truncates only that
        # padding, never narration. Scene windows ceil the terminal boundary so
        # video >= narration end, so no spoken word is ever clipped.
        "-af", "apad",
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
    section_cards: bool = False,
    section_transitions: bool = False,
    card_seconds: float = SECTION_CARD_SECONDS,
    card_comp: str = SECTION_CARD_COMP,
    output_name: str = "final.mp4",
) -> str:
    """Full assembly: audio → clips → concat → subtitles → mux → <output_name>

    transition: "cut" (default) or "fade" — per-clip fade-in/out against black.
    ken_burns: when True, applies a slow zoom to PNG (still-image) scenes only.
    Both kwargs become DEFAULTS for EDL auto-generation when no edl.json
    exists yet; once an EDL is present, its per-scene values are
    authoritative and these kwargs are ignored.

    section_cards: when True, front each section-intro scene (first scene of each
    body segment) with a title card that eats into THAT scene's own frames — the
    total length, and therefore the audio + subtitle timelines, are unchanged.
    Karaoke cues that play entirely under a card are suppressed. Default False
    renders the plain path (byte-identical to before). card_seconds / card_comp
    set the card length + Remotion comp. output_name: filename inside video/, so
    a card render can write beside an untouched final.mp4.

    section_transitions: when True (and section_cards is False), blend a short
    crossfade across each section boundary (segment_id change) via
    concat_clips_crossfade instead of a hard cut. Duration-neutral (each blended
    pair still emits Fa+Fb frames), so the audio + subtitle timelines are
    unchanged. If both section_cards and section_transitions are set, cards win
    (a card-handoff crossfade is a later step) and section_transitions is ignored
    with a warning."""
    if transition not in ("cut", "fade"):
        raise ValueError(f"transition must be 'cut' or 'fade', got {transition!r}")

    cards = derive_section_cards(project_name) if section_cards else {}
    if cards and section_transitions:
        print(
            "  WARN: section cards and section transitions both requested; "
            "section cards win (card-handoff crossfade is a later step) — "
            "ignoring section transitions."
        )

    print("  Assembling audio...")
    audio = assemble_audio(project_name)

    print("  Rendering scene clips...")
    clips = render_all_scene_clips(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
        section_cards=cards or None, card_seconds=card_seconds, card_comp=card_comp,
    )

    print("  Concatenating clips...")
    if cards:
        silent = concat_clips(project_name, clips)
    elif section_transitions:
        silent = concat_clips_crossfade(
            project_name, clips, footage_paths,
            transition=transition, ken_burns=ken_burns,
        )
    else:
        silent = concat_clips(project_name, clips)

    # Windows covered by a section card, so the subtitle builder can suppress any
    # karaoke cue that would otherwise render over a card. Each window is
    # [scene start_time, start_time + card_frames/FPS] using the SAME frame math
    # render_section_intro_clip uses, so the window's right edge lands exactly on
    # the card→footage seam. None when cards are off (subtitles unchanged).
    blank_windows = None
    if cards:
        windows_by_id = {s["id"]: s for s in load_scene_windows(project_name)}
        blank_windows = []
        for sid in cards:
            s = windows_by_id[sid]
            scene_frames = _scene_frame_count(s)
            card_frames = min(round(card_seconds * FPS), scene_frames)
            start = s["start_time"]
            blank_windows.append((start, round(start + card_frames / FPS, 3)))

    print("  Building subtitles...")
    sub_path = build_subtitles(
        project_name,
        str(PROJECTS_ROOT / project_name / "video" / "subtitles.ass"),
        blank_windows=blank_windows,
    )

    print("  Muxing audio + burning subtitles...")
    final = mux_audio(
        project_name, silent, audio,
        subtitle_path=sub_path, output_name=output_name,
    )

    return final
