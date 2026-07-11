import json
import os
import subprocess
from pathlib import Path

from services.channel_registry import resolve_channel_editing
from services.edl_service import (
    EDL_SCHEMA_VERSION,
    generate_default_edl,
    is_current_version,
    load_edl,
    save_edl,
)
from services.graphics_registry import (
    resolve_section_header_default,
    resolve_title_card_default,
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
# the assembled video length is unchanged. SECTION_CARD_SECONDS is now only a
# FALLBACK: the real per-card hold is computed from the narration
# (_card_seconds_by_scene) so the card stays up until its spoken line finishes.
SECTION_CARD_SECONDS = 2.5
SECTION_CARD_COMP = "GardenBand"

# Beat held on a card AFTER its narrated line's last spoken word ends, before it
# cuts to footage — so the line lands and settles rather than the card snapping
# away on the final syllable. ~0.35s reads as a natural breath. In practice the
# section-intro / title scene carries only its opener line, so the card ends up
# filling (essentially) the whole intro scene, and this beat is the short
# inter-scene gap between the line and the next scene's narration.
CARD_LINE_BEAT = 0.35

# Ken Burns (subpixel warp) engine. Each PNG scene is resampled ONCE per output
# frame with an OpenCV affine warp (cv2.warpAffine) at FRACTIONAL source
# coordinates — genuine sub-pixel sampling with NO supersample canvas. The prior
# chain (supersample → per-frame scale=eval=frame → INTEGER crop) snapped the
# focal window to an integer grid every frame, so a slow zoom stuttered; warping
# from the native source at float coords removes that grid entirely. The warp
# math is ported (copied) from tools/kenburns_subpixel.py — services must not
# import from tools — and cv2/numpy are imported LAZILY inside the KB path so
# importing this module for non-KB / API use never needs them.
#
# KB_DEFAULT_MOTION = (z0, z1, cx0, cy0, cx1, cy1): a slow center zoom-in
# 1.0→1.10 with the focal center held at 0.5,0.5. Every scene gets this default
# today; call sites pass no motion, and per-scene variety is a later iteration.
# KB_DEFAULT_EASING = "linear" (constant velocity, pe = p) reproduces the
# approved centerzoom_new.mp4 reference exactly; "smoothstep" is also supported
# by the easing helper.
KB_DEFAULT_MOTION = (1.00, 1.10, 0.50, 0.50, 0.50, 0.50)
KB_DEFAULT_EASING = "linear"

# Subpixel-warp interpolation, env-overridable. "cubic" → cv2.INTER_CUBIC
# (faster); anything else → cv2.INTER_LANCZOS4 (default, sharpest). Resolved to
# the cv2 flag lazily inside the KB path so importing this module never needs cv2.
RENDER_KB_INTERP = os.environ.get("RENDER_KB_INTERP", "lanczos4")

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
# v11: Ken Burns engine swap — the supersample→scale=eval=frame→integer-crop
#      chain is replaced by a per-frame subpixel cv2.warpAffine; the key gains a
#      motion_sig (motion + easing + interp) so a KB motion/easing/interp change
#      re-renders only the affected clips.
_CLIP_CACHE_VERSION = 11

# Per-clip fade-in/out duration when transition="fade". 0.15s in + 0.15s out
# per clip keeps total video duration unchanged (audio stays in sync) and
# produces a soft dip-through-black between scenes.
FADE_DUR = 0.15

# Fade-to-black width (in frames) applied at each section-boundary seam when
# section_transitions is on and the incoming scene's EDL lead_in is ``fade_black``
# (the section starts + the conclusion, + a mid-hook title scene). 28 frames ==
# 1.12s at 25 fps: a long-ish, GENTLE fade THROUGH black — the picture dips to
# black at the ORIGINAL cut (the fade's centre, sitting in the section-boundary
# silence) and the incoming section/title card then rises FROM black. Even, so the
# half-width (14) added to BOTH clips flanking a seam is exact and the blended pair
# still emits exactly Fa+Fb frames (total video length — and therefore the audio +
# subtitle timelines — stay unchanged). This is the everyday section treatment,
# not a hard slam. Distinct from FADE_DUR (per-clip dip-to-black) and from the
# mid-tier ``blur_dissolve`` below.
SECTION_FADEBLACK_FRAMES = 28

# Mid-tier blur-dissolve (defocus dissolve) params. A ``blur_dissolve`` lead_in
# (edl_service's within-segment visual-subject-shift classifier) marks a seam where
# concat_clips_crossfade defocus-dissolves the two flanking clips in place of the
# cut. BLUR_DISSOLVE_FRAMES == N: built on the SAME extend-and-overlap mechanic as
# the section fade — each flanking clip is re-rendered +N frames of REAL footage and
# the pair is blended over a CENTERED 2N-frame overlap on the original cut, so every
# frame in the transition is a real footage frame at NORMAL SPEED (no setpts slowdown
# / frame duplication — the earlier slowed-window build stuttered on stock-video
# motion). The overlap is an EASED cross-dissolve PLUS a ramped Gaussian defocus (A
# blurs 0->peak as it is covered, B peak->0 as it resolves), so the seam reads
# sharp -> soft -> sharp. Because each pair still emits exactly Fa+Fb frames it is
# duration-neutral, like the fade. ~10 frames (0.8s @25fps) reads a tier above a hard
# cut but clearly below the 28-frame section fade. Everything runs on the pipeline's
# OWN clips in ffmpeg — NOT a Chromium/Remotion round trip — so the transition shares
# the surrounding footage's exact colour pipeline and single-generation quality and
# leaves no colour/brightness seam at either edge of the overlap.
BLUR_DISSOLVE_FRAMES = 10
# Peak defocus blur at each layer's far end of the dissolve, as a gblur sigma in px
# @1080p (== the CSS-blur radius the /remotion blurDissolve presentation uses, so
# the look matches); roughly half this is visible at the mid-dissolve crossover.
BLUR_DISSOLVE_MAX_BLUR = 36

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


def _motion_signature(
    motion: tuple[float, float, float, float, float, float],
    easing: str,
    interp: str,
) -> str:
    """Stable signature of the Ken Burns warp params (focal move + easing +
    interpolation) for the clip cache key, so changing a scene's motion, the
    default easing, or RENDER_KB_INTERP re-renders only the affected KB clips.
    Non-KB clips pass the module defaults and never warp, so the value is a
    constant for them (harmless — the cache_version bump already invalidates
    pre-swap clips once)."""
    return json.dumps(
        {"motion": list(motion), "easing": easing, "interp": interp},
        sort_keys=True,
    )


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
    motion_sig: str = "",
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
        and cache.get("motion_sig") == motion_sig
        and cache.get("cache_version") == _CLIP_CACHE_VERSION
    )


def _kb_smoothstep(p: float) -> float:
    """Smoothstep easing (ported from tools/kenburns_subpixel.py)."""
    return p * p * (3.0 - 2.0 * p)


def _kb_pe(p: float, easing: str) -> float:
    """Eased progress (ported). 'smoothstep' for restrained moves; 'linear'
    (pe = p) for the constant-velocity center zoom that matches the approved
    reference render."""
    return _kb_smoothstep(p) if easing == "smoothstep" else p


def _kb_warp_matrix(
    src_w: int, src_h: int,
    move: tuple[float, float, float, float, float, float], p: float, easing: str,
):
    """The 2x3 affine mapping the eased focal source window onto the full
    OUT_W x OUT_H frame at progress p (ported from tools/kenburns_subpixel.py).
    Scale s and offsets x0/y0 are floats, so warpAffine samples the source at
    fractional coords — subpixel, no supersample."""
    import numpy as np  # lazy: only the KB PNG path needs numpy

    z0, z1, cx0, cy0, cx1, cy1 = move
    pe = _kb_pe(p, easing)
    Z = z0 * (z1 / z0) ** pe  # exponential zoom (constant perceptual rate)
    cx = cx0 + (cx1 - cx0) * pe
    cy = cy0 + (cy1 - cy0) * pe
    base = max(OUT_W / src_w, OUT_H / src_h)  # fill 16:9 from the source
    s = base * Z
    win_w = OUT_W / s
    win_h = OUT_H / s
    x0 = cx * (src_w - win_w)  # in-bounds for cx,cy in [0,1]
    y0 = cy * (src_h - win_h)
    return np.array([[s, 0.0, -x0 * s], [0.0, s, -y0 * s]], dtype=np.float64)


def _render_kenburns_png(
    footage_path: str,
    output_path: str,
    *,
    frames: int,
    motion: tuple[float, float, float, float, float, float],
    easing: str,
    vf: str,
) -> None:
    """Subpixel Ken Burns encode for a PNG scene (frame-writer ported from
    tools/kenburns_subpixel.py — services must not import from tools).

    Resamples the still ONCE per output frame with cv2.warpAffine at fractional
    source coords (genuine sub-pixel sampling, no supersample canvas) and streams
    the raw BGR frames to a single libx264 encode. Generates EXACTLY ``frames``
    frames (p = n/(frames-1), or 0 when frames==1) — the audio-sync contract every
    clip path shares. The warp already produces the final OUT_W x OUT_H canvas, so
    ``vf`` carries only pixel-format + the shared fade/overlays (no scale/crop/
    zoom). cv2 reads BGR, so the frames pipe out as bgr24 with no channel swap.
    cv2/numpy are imported lazily so importing this module never needs OpenCV."""
    import cv2  # lazy: only the KB PNG path needs OpenCV
    import numpy as np

    interp = cv2.INTER_CUBIC if RENDER_KB_INTERP == "cubic" else cv2.INTER_LANCZOS4

    src = cv2.imread(str(footage_path), cv2.IMREAD_COLOR)  # BGR (piped as bgr24)
    if src is None:
        raise RuntimeError(f"Ken Burns: could not read still {footage_path}")
    src_h, src_w = src.shape[:2]
    denom = frames - 1 if frames > 1 else 1

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{OUT_W}x{OUT_H}", "-framerate", str(FPS),
            "-i", "-",
            "-vf", vf,
            "-frames:v", str(frames),
            "-an", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            output_path,
        ],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        for n in range(frames):
            p = (n / denom) if frames > 1 else 0.0
            M = _kb_warp_matrix(src_w, src_h, motion, p, easing)
            frame = cv2.warpAffine(
                src, M, (OUT_W, OUT_H),
                flags=interp, borderMode=cv2.BORDER_REFLECT_101,
            )
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    except BrokenPipeError:
        pass  # ffmpeg exited early; its stderr (read below) carries the reason
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(
            f"Ken Burns ffmpeg encode failed ({output_path}):\n{err}"
        )


def render_scene_clip(
    scene: dict,
    footage_path: str,
    output_path: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
    motion: tuple | None = None,
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

    ken_burns: when True AND the source is a PNG (still image), animate a
      subpixel Ken Burns move (default: a slow center zoom 1.0 -> 1.10) by
      warping the still once per frame with cv2.warpAffine straight to the
      final 1920x1080 canvas (see _render_kenburns_png). MP4 sources are
      untouched — they already have motion — and keep the plain fit-to-fill
      encode.

    motion: optional (z0, z1, cx0, cy0, cx1, cy1) Ken Burns move; defaults to
      KB_DEFAULT_MOTION. Only used on the Ken Burns PNG path. Call sites pass
      nothing today, so every scene gets the default center zoom; per-scene
      variety is a later iteration.

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

    # Resolve the Ken Burns move (call sites pass nothing today → every scene
    # gets the default center zoom). motion_sig keys the cache on the warp params
    # so a motion / easing / interp change re-renders only the affected KB clips.
    motion = motion or KB_DEFAULT_MOTION
    motion_sig = _motion_signature(motion, KB_DEFAULT_EASING, RENDER_KB_INTERP)

    if _clip_cache_hit(
        scene, footage_path, output_path, transition, ken_burns,
        overlays=overlays, edit_style=edit_style, motion_sig=motion_sig,
    ):
        return  # cache hit — output already valid

    is_png = str(footage_path).lower().endswith(".png")
    kb_png = ken_burns and is_png

    # Ken Burns ON + PNG source → subpixel warp (encoded below). The warp
    # resamples the still straight to the final OUT_W x OUT_H canvas per frame, so
    # the ffmpeg vf here carries NO scale/crop/zoom — only pixel-format, plus the
    # shared fade + overlays appended below. Every other case (video source, or KB
    # off) keeps the unchanged fit-to-fill + fps + format chain and the subprocess
    # encode.
    if kb_png:
        filters = ["format=yuv420p"]
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

    if kb_png:
        # Subpixel Ken Burns: warp each frame from the native still and pipe the
        # raw BGR frames through the vf (format + fade + overlays) to libx264.
        _render_kenburns_png(
            footage_path, output_path,
            frames=frames, motion=motion, easing=KB_DEFAULT_EASING, vf=vf,
        )
    else:
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
            "motion_sig": motion_sig,
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
    motion: tuple | None = None,
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
        transition=transition, ken_burns=ken_burns, motion=motion,
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
    item_noun: str = "",
    duration: float = SECTION_CARD_SECONDS,
    comp: str = SECTION_CARD_COMP,
    props: dict | None = None,
) -> str:
    """Render one Remotion section-header card to a silent MP4 at ``out_path``.

    Reuses the SAME renderer the /remotion tab drives (frontend
    scripts/render-remotion.mjs) via subprocess, cwd=<frontend>. ``props`` is the
    channel's resolved section-header default design (resolve_section_header_-
    default); this function copies it and overrides ``index`` + ``itemNoun`` +
    ``title`` from the EDL card content, blanks ``subtitle`` so the card shows
    only the numbered section title, and forces ``durationInSeconds`` to the
    card's frame-quantized length so the animation is timed to what's actually
    shown. ``item_noun`` (e.g. "Flower" / "Mistake") lets the card render a
    "{itemNoun} #{index}." label; empty is fine (the card shows the bare index).
    Everything else (palette / background / decoration / fontFamily / animation)
    comes from the preset, so nothing falls back to the designer's demo props.
    ``props=None`` passes only the overridden keys and lets the comp supply its
    own defaults. The raw card renders at the comp's native 30 fps;
    _normalize_card_to_clip resamples it to the canonical 25 fps / 1920x1080 /
    yuv420p / SAR 1:1 shape and caps it to exact frames."""
    card_props = dict(props or {})
    card_props["index"] = str(index)
    card_props["itemNoun"] = item_noun
    card_props["title"] = title
    card_props["subtitle"] = ""  # title-only card (blank any preset subtitle)
    card_props["durationInSeconds"] = float(duration)
    cmd = [
        "node", str(RENDER_SCRIPT),
        f"--comp={comp}",
        f"--props={json.dumps(card_props)}",
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


# ---------------------------------------------------------------------------
# Mid-tier blur-dissolve (pure-ffmpeg defocus dissolve on a within-segment seam)
#
# A ``blur_dissolve`` lead_in marks an ordinary within-segment cut where the
# visual subject shifts (edl_service). At that seam concat_clips_crossfade
# defocus-dissolves the two flanking CLIPS on the SAME extend-and-overlap mechanic
# the section fade uses: each clip is re-rendered +N frames of REAL footage
# (render_extended_clip) and the pair is blended over a CENTERED 2N-frame overlap on
# the original cut — an EASED cross-dissolve plus a ramped Gaussian defocus, driven
# per-frame by sendcmd (_blur_dissolve_sendcmd). Every frame in the transition is a
# real footage frame at NORMAL SPEED (no slowdown / duplication), and the pair still
# emits Fa+Fb frames, so the assembled length — and the audio + subtitle timelines —
# stay unchanged (duration-neutral, exactly like the fade). Running on the pipeline's
# own clips (rather than a Chromium/Remotion render of them, which decodes +
# re-encodes through a different colour matrix and an extra generation) keeps it in
# the SAME colour space and single generation as the surrounding footage, so neither
# edge of the overlap shows a jump. The helpers below supply the shared easing and
# the per-frame defocus-ramp sendcmd string.
# ---------------------------------------------------------------------------

def _blur_dissolve_inoutquint(t: float) -> float:
    """The ``inOutQuint`` easing (the strongBezier-equivalent curve the /remotion
    blurDissolve used): a long flat ramp-in, a steep middle, a flat settle. Drives
    BOTH the defocus ramp and the opacity crossfade so the window's softest,
    most-blended instant lands mid-dissolve."""
    return 16 * t ** 5 if t < 0.5 else 1 - ((-2 * t + 2) ** 5) / 2


def _blur_dissolve_sendcmd(to_peak: bool, start_frame: int, count: int) -> str:
    """Per-frame ``gblur sigma`` commands that ramp a blur-dissolve's defocus across
    its ``count``-frame overlap (count == 2N), formatted for a ``sendcmd`` filter
    driving one side's gblur.

    Each command fires at a frame's own timestamp on that side's timeline: clip A's
    tail overlap begins at ``start_frame`` == Fa-N (its last 2N frames), clip B's head
    overlap begins at ``start_frame`` == 0 (its first 2N frames). ``to_peak`` -> clip
    A (sharp->soft as it is covered, sigma 0->peak); else clip B (soft->sharp as it
    resolves, peak->0). Both ramp on the SAME inOutQuint easing as the opacity
    cross-dissolve so the softest, most-blended instant lands mid-overlap; the peak is
    BLUR_DISSOLVE_MAX_BLUR (reached at each side's far end, ~half visible at the
    crossover — the approved blurDissolve look). gblur sigma must be > 0, so a "sharp"
    frame floors at a no-op 0.01 — the same value gblur holds OUTSIDE the overlap, so
    the frames flanking the overlap stay sharp and neither edge shows a blur on/off
    seam."""
    peak = float(BLUR_DISSOLVE_MAX_BLUR)
    denom = max(1, count - 1)
    cmds = []
    for j in range(count):
        e = _blur_dissolve_inoutquint(j / denom)
        sigma = peak * e if to_peak else peak * (1 - e)
        t = (start_frame + j) / FPS
        cmds.append(f"{t:.4f} gblur sigma {max(0.01, sigma):.4f}")
    return ";".join(cmds)


def _concat_segments_copy(
    segs: list[str], output_path: str, base: str, *, reencode: bool = False,
) -> str:
    """Join already-canonical segments with the concat demuxer (stream copy).

    Both the card segment and the footage segment are encoded to the identical
    canonical shape (1920x1080 / 25 fps / yuv420p tv-range / SAR 1:1 / tb
    1/12800), so a stream copy preserves every frame with no re-encode. If the
    demuxer ever refuses the seam, fall back to a concat-filter re-encode of just
    this 2-segment join (re-normalizing each input) and note it.

    ``reencode=True`` skips the stream-copy attempt and goes straight to the
    concat-filter re-encode. Required when the result will later be DECODED by
    another filter graph (the section crossfade's xfade/concat filters): the
    concat-demuxer stream copy leaves the joined h264's DTS layout such that a
    downstream decode-based filter reads the internal card→footage seam as EOF
    and silently drops the rest (and any clip concatenated before it). The
    re-encode regenerates a clean, single-segment stream those filters consume in
    full. The demuxer concat path (concat_clips) reads packets without decoding,
    so it is immune and keeps the fast lossless copy (default ``reencode=False``)."""
    if not reencode:
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
    item_noun: str = "",
    card_seconds: float = SECTION_CARD_SECONDS,
    card_comp: str = SECTION_CARD_COMP,
    card_props: dict | None = None,
    transition: str = "cut",
    ken_burns: bool = False,
    motion: tuple | None = None,
    overlays: list[dict] | None = None,
    edit_style: dict | None = None,
    reencode: bool = False,
) -> str:
    """Render a section-intro scene as ``[card | card_frames] ++ [footage |
    footage_frames]`` where ``card_frames + footage_frames == scene['frames']``
    EXACTLY, written to ``output_path`` (``scene_{sid:03d}.card.mp4``).

    ``reencode`` is forwarded to _concat_segments_copy: pass True when the result
    feeds a later decode-based filter graph (the section crossfade) so the joined
    clip is a clean single-segment stream (see _concat_segments_copy).

    ``card_frames = min(round(card_seconds * FPS), scene_frames)``: the card eats
    into the scene's own frames and NEVER spans into the next scene, so the total
    video length is unchanged. On the clamp (scene_frames <= card_frames) the
    card fills the whole scene and there is no footage segment. The footage
    segment renders through the normal render_scene_clip path (Ken Burns / fade /
    any remaining overlays apply) at the shortened frame count, with the header +
    counter overlays already stripped by the caller — the card now carries the
    section number (its badge) + the title. ``card_comp`` + ``card_props`` are the
    channel's resolved section-header design (comp + props); render_section_card
    overlays ``index`` + ``item_noun`` + ``title`` onto them (``item_noun`` drives
    the card's "{itemNoun} #{index}." label; empty shows the bare index). The card
    hard-cuts into the footage; the scene's own transition is passed to the
    footage segment."""
    scene_frames = _scene_frame_count(scene)
    card_frames = min(round(card_seconds * FPS), scene_frames)
    footage_frames = scene_frames - card_frames

    base = os.path.splitext(output_path)[0]  # …/scene_013.card
    raw_card = base + ".raw.mp4"
    card_seg = base + ".cardseg.mp4"
    foot_seg = base + ".footseg.mp4"

    render_section_card(
        index, title, raw_card,
        item_noun=item_noun,
        duration=card_seconds, comp=card_comp, props=card_props,
    )
    _normalize_card_to_clip(raw_card, card_frames, card_seg)

    segs = [card_seg]
    if footage_frames > 0:
        render_scene_clip(
            {**scene, "frames": footage_frames}, footage_path, foot_seg,
            transition=transition, ken_burns=ken_burns, motion=motion,
            overlays=overlays, edit_style=edit_style,
        )
        segs.append(foot_seg)

    _concat_segments_copy(segs, output_path, base, reencode=reencode)
    return output_path


def _cards_from_edl(edl: dict, channel_id: str | None) -> dict[int, dict]:
    """Map ``scene_id -> {"index", "item_noun", "title", "comp", "props"}`` for
    every EDL scene carrying a ``card`` — the section-intro scenes
    (``role:"section_header"``) and the mid-hook title scene (``role:"title"``).

    The EDL persists only each card's ``comp`` + per-video ``content`` (a section
    card's ``{index,item_noun,title}``, a title card's ``{title}``); the
    render-time design ``props`` (and comp) RE-RESOLVE here from the channel's
    DEFAULT for that card's ROLE so a design edit re-renders the cards without
    regenerating the EDL. Section headers resolve to a ROTATION SET (an ordered
    list of {comp,props}, resolve_section_header_default); each section card
    re-picks its rotated design by section POSITION — its ``index`` minus one,
    which equals the seg_id the EDL generator rotated on — as ``pos % len``, so
    the per-section comps match generation AND track a rotation edit without an
    EDL regen. The title card resolves to a single {comp,props}
    (resolve_title_card_default) and never rotates. A card whose role has no
    channel default is SKIPPED (inert), matching the EDL generator, which only
    emits a role's cards when that role's default is set. A title card carries no
    index/item_noun (its content has only a title), so both resolve to "". A card
    whose content has no title is skipped."""
    # Section headers → rotation set (list); title card → single {comp,props}.
    # Both re-resolve here so a design edit (or a rotation change) re-renders the
    # cards without an EDL regen.
    section_rotation = resolve_section_header_default(channel_id)  # list | None
    title_default = resolve_title_card_default(channel_id)          # dict | None
    cards: dict[int, dict] = {}
    for entry in edl.get("scenes", []):
        card = entry.get("card")
        if not card:
            continue
        content = card.get("content") or {}
        title = (content.get("title") or "").strip()
        if not title:
            continue
        role = card.get("role")
        if role == "section_header":
            if not section_rotation:
                continue
            # Re-pick the rotated design by section position (index-1 == the
            # generator's seg_id) so it matches what generate_default_edl
            # assigned and wraps identically past the end of the set.
            try:
                pos = int(str(content.get("index", "")).strip()) - 1
            except ValueError:
                pos = 0
            design = section_rotation[pos % len(section_rotation)]
        elif role == "title":
            if not title_default:
                continue
            design = title_default
        else:
            continue
        cards[entry["id"]] = {
            "index": str(content.get("index", "")),
            "item_noun": (content.get("item_noun") or "").strip(),
            "title": title,
            "comp": design["comp"],
            "props": design["props"],
        }
    return cards


def _card_seconds_by_scene(
    project_name: str, cards: dict[int, dict], default: float,
) -> dict[int, float]:
    """Seconds to hold each card: from its scene's start until the card's
    NARRATED line's last spoken word ends, plus ``CARD_LINE_BEAT``.

    The section-intro / title scene carries EXACTLY the card's line — the
    ``title_spoken`` for the title card, the ``"{item_noun} number N. {title}"``
    opener for a section header (verified: each such scene's narration is just
    that line) — so the scene's last spoken word IS the line's last word, and the
    following scene's narration opens the next clip. We therefore find, per card
    scene, the last audio word that starts before the NEXT scene's start, and
    hold from this scene's start to that word's end plus the beat. Using the last
    WORD end (not the frame-quantized scene edge) keeps the card off the short
    silent gap that precedes the next narration.

    Boundaries come from the frame-quantized scene starts (scene_windows.json);
    word ends come from the word-level audio_timeline. A half-frame tolerance
    keeps the boundary comparison on the correct side of a quantized edge. Falls
    back to ``default`` for a card scene with no following scene or no locatable
    words (neither happens for section-intro cards, which are never the last
    scene)."""
    windows = load_scene_windows(project_name)
    timeline = load_audio_timeline(project_name)
    all_words = sorted(
        (w for chunk in timeline for w in chunk["words"]),
        key=lambda w: w["global_start"],
    )
    pos_by_id = {s["id"]: i for i, s in enumerate(windows)}
    tol = 0.5 / FPS  # half a frame — stay on the correct side of a quantized edge
    out: dict[int, float] = {}
    for sid in cards:
        i = pos_by_id.get(sid)
        if i is None or i + 1 >= len(windows):
            out[sid] = default
            continue
        start = windows[i]["start_time"]
        boundary = windows[i + 1]["start_time"]
        last_end = None
        for w in all_words:
            if w["global_start"] >= boundary - tol:
                break
            last_end = w["global_end"]
        if last_end is None or last_end <= start:
            out[sid] = default
            continue
        out[sid] = round((last_end - start) + CARD_LINE_BEAT, 3)
    return out


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

    ``section_cards`` (optional): ``{scene_id: {"index", "title", "comp",
    "props"}}`` from ``_cards_from_edl``. Each listed scene is rendered as a title
    card fronting a shortened footage segment (render_section_intro_clip →
    scene_{sid}.card.mp4) instead of a plain clip, and that ``.card.mp4`` path is
    returned in its slot so the downstream concat picks it up. Each card's
    ``comp`` + ``props`` (the channel's resolved section-header design) drive the
    look and ``index`` + ``title`` fill the badge. ``None`` (default) renders
    every scene the plain way — byte-identical to the pre-card path.
    ``card_seconds`` sets the card length; ``card_comp`` is only a fallback when a
    card omits its own comp."""
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
            # Title cards carry no index; omit the "{index}. " prefix then.
            label = (
                f"{card['index']}. {card['title']}"
                if card["index"] else card["title"]
            )
            print(f"  Rendering section card + clip: scene {sid} ({label})...")
            render_section_intro_clip(
                scene, src, out_card,
                index=card["index"], title=card["title"],
                item_noun=card.get("item_noun", ""),
                card_seconds=card.get("card_seconds", card_seconds),
                card_comp=card.get("comp", card_comp),
                card_props=card.get("props"),
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


def _lead_in_seams(windows: list[dict], edl_by_id: dict[int, dict]) -> list[int]:
    """Left indices ``i`` where the NEXT scene (``windows[i+1]``) enters via a
    NON-CUT lead_in — its EDL ``lead_in.type`` is not ``"cut"`` (a ``fade_black``
    section boundary OR a mid-tier ``blur_dissolve``). A non-cut lead_in INTO the
    scene at list position ``i+1`` becomes a seam between clips ``i`` and ``i+1``;
    the caller then treats each seam per its lead_in type (a fade_black extends +
    xfades the two flanking clips THROUGH black; a blur_dissolve extends +
    defocus-dissolves them over a centered overlap). Scene 0 has no preceding clip, so its lead_in (a cut for the
    hook's first scene) can never open a seam.

    The EDL derives a ``fade_black`` lead_in at every section_start + the conclusion
    and a ``blur_dissolve`` at qualifying within-segment subject shifts
    (edl_service), so this reproduces the section-boundary seam set the previous
    hardcoded segment_id-change scan produced — now sourced from the EDL so the
    edit decisions live in one place (the EDL), configurable per scene.

    Raises NotImplementedError if two seams are adjacent (consecutive left
    indices differ by 1): that shared clip would have to feed two transitions at
    once, which this step does not support. The EDL's classifier guarantees no two
    non-cut seams are adjacent (a section is never a single scene here, and the
    blur-dissolve classifier never places a dissolve next to another non-cut seam),
    so this never fires — it stays a loud guard against a future regression."""
    seams = [
        idx - 1
        for idx in range(1, len(windows))
        if (
            (edl_by_id.get(windows[idx]["id"], {}).get("lead_in") or {})
            .get("type", "cut")
            != "cut"
        )
    ]
    for a, b in zip(seams, seams[1:]):
        if b - a == 1:
            raise NotImplementedError(
                f"Adjacent section boundaries at clip indices {a} and {b} "
                f"(a single-scene section): that clip would participate in two "
                f"crossfades at once, which section transitions do not support."
            )
    return seams


def _count_video_frames(path: str) -> int:
    """Exact video frame count from the container's sample table (instant — no
    decode). ffmpeg-written libx264 mp4 always carries an accurate ``nb_frames``,
    so this matches a ``-count_frames`` decode without the decode cost."""
    out = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames", "-of", "default=nk=1:nw=1",
        os.path.abspath(path),
    ], check=True, capture_output=True, text=True).stdout.strip()
    return int(out)


def concat_clips_crossfade(
    project_name: str,
    clip_paths: list[str],
    footage_paths: dict,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
    section_cards: dict | None = None,
    card_seconds: float = SECTION_CARD_SECONDS,
    card_comp: str = SECTION_CARD_COMP,
) -> str:
    """Join scene clips, blending a short fade-to-black INTO each scene the EDL
    marks with a ``fade_black`` ``lead_in`` (the section starts + the conclusion,
    + a mid-hook title scene — _lead_in_seams). At each seam the two flanking clips
    are re-rendered +SECTION_FADEBLACK_FRAMES//2 frames and joined with an
    ``xfade=transition=fadeblack`` centered on the ORIGINAL cut (the picture dips
    THROUGH black at the cut); every other clip passes through untouched. Because
    each blended pair still emits exactly Fa+Fb frames, the assembled length — and
    therefore the audio + subtitle timelines — are unchanged.

    ``section_cards`` (optional; ``{scene_id: {"index","title","comp","props"}}``
    from _cards_from_edl): a flanking clip that is one of these section-intro CARD
    scenes is re-rendered CARD-FRONTED (render_section_intro_clip ->
    scene_{id}.card.xfade.mp4) rather than plain, so the previous section's footage
    fades to black and the header card rises FROM black — cards and fades COEXIST.
    The +half frames
    lengthen only that clip's footage segment (card_frames stays the card's own
    budget, so the blend lands wholly on the card and the card is otherwise
    untouched), so the pair still emits Fa+Fb frames. A plain flanking clip goes
    to scene_{id}.xfade.mp4 as before. ``None`` renders every seam plain.

    A scene the EDL marks with a ``blur_dissolve`` lead_in (a mid-tier
    within-segment subject shift) uses the SAME extend-and-overlap mechanic as the
    fade, minus the dip-to-black: both flanking clips are re-rendered
    +BLUR_DISSOLVE_FRAMES (N) frames of REAL footage and blended over a CENTERED
    2N-frame overlap on the original cut — an EASED cross-dissolve plus a ramped
    Gaussian defocus (A blurs 0->peak as it is covered, B peak->0 as it resolves), so
    the seam reads sharp -> soft -> sharp on real footage at NORMAL SPEED (no slowdown
    / duplicated frames). Each pair still totals Fa+Fb, so this is duration-neutral
    exactly like the fade. A blur-dissolve seam never lands on a section-card clip
    (those are section starts, whose fade lead_in would make the seam adjacent —
    the classifier excludes that), so its flanking clips are always plain.

    Unlike concat_clips (concat demuxer, stream copy) this re-encodes: the xfade
    filter can't run on the demuxer, so every input is normalized via the shared
    _normalize_video_chain and the whole thing runs through one concat FILTER
    graph. With no crossfade lead_ins it delegates to concat_clips. Writes the same
    video/video_no_audio.mp4 sink as concat_clips (so the downstream mux is
    unchanged) and returns its path."""
    windows = load_scene_windows(project_name)

    # Resolve per-scene render params exactly as render_all_scene_clips does so
    # each extended seam clip matches its plain counterpart (bar the +frames).
    # Loaded up front because the crossfade SEAMS are now derived from the EDL
    # (each scene's ``lead_in``), not from a segment_id scan.
    edl = _load_or_create_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    edl_by_id: dict[int, dict] = {e["id"]: e for e in edl.get("scenes", [])}
    seams = _lead_in_seams(windows, edl_by_id)
    if not seams:
        # No crossfade lead_ins (e.g. a single-segment project, or the EDL marks
        # every scene as a cut) — nothing to blend; fall back to the plain
        # demuxer concat.
        return concat_clips(project_name, clip_paths)

    if len(clip_paths) != len(windows):
        raise ValueError(
            f"clip_paths ({len(clip_paths)}) and scene windows ({len(windows)}) "
            f"length mismatch — cannot align section-crossfade seams."
        )

    edit_style = resolve_channel_editing(_project_channel_id(project_name))
    cards = section_cards or {}

    clips_dir = str(PROJECTS_ROOT / project_name / "clips")
    half = SECTION_FADEBLACK_FRAMES // 2

    # Split the non-cut seams by their incoming lead_in.type: a ``fade_black``
    # (section boundary) extends both flanking clips and xfades them THROUGH black; a
    # ``blur_dissolve`` (mid-tier within-segment subject shift) extends both flanking
    # clips and defocus-dissolves them over a centered overlap. The classifier
    # guarantees no two non-cut seams are adjacent (enforced by _lead_in_seams), so no
    # clip ever flanks two seams — the two extend mechanics never contend for the same
    # clip.
    def _incoming_type(i: int) -> str:
        return (
            (edl_by_id.get(windows[i + 1]["id"], {}).get("lead_in") or {})
            .get("type", "cut")
        )
    fade_seams = [i for i in seams if _incoming_type(i) == "fade_black"]
    blur_seams = [i for i in seams if _incoming_type(i) == "blur_dissolve"]

    # Render the two extended clips flanking each FADE seam, override those two input
    # slots with the extended paths, and record the xfade offset: the blend
    # starts at (Fa - half)/FPS into clip A (A's original frame count is Fa) so
    # its centre — the full-black instant — lands on the original cut at frame Fa.
    # A flanking clip that is a section-intro CARD scene is re-rendered CARD-FRONTED
    # (render_section_intro_clip -> .card.xfade.mp4) so the previous footage fades
    # to black and the card rises FROM black; the +half lengthens only its footage
    # segment (card_frames stays the card's budget, so the whole blend lands on the
    # card), and it still totals Fb+half.
    input_paths = list(clip_paths)
    seam_offsets: dict[int, float] = {}
    for i in fade_seams:
        for j in (i, i + 1):
            scene = windows[j]
            sid = scene["id"]
            src = footage_paths.get(sid)
            if not src or not os.path.exists(src):
                raise FileNotFoundError(f"No footage for scene {sid}")
            entry = edl_by_id.get(sid, {})
            per_transition = entry.get("transition", transition)
            per_ken_burns = entry.get("ken_burns", ken_burns)
            overlays = entry.get("overlays", [])
            card = cards.get(sid)
            if card:
                # Card scene on a seam: extend the CARD-FRONTED clip (not a plain
                # one) so the blend lands on the card. Bumping the scene's frame
                # count by +half feeds render_section_intro_clip a longer footage
                # segment while card_frames is unchanged. Header/counter overlays
                # are stripped (the card badge carries the number + title), as in
                # render_all_scene_clips' card path.
                out = os.path.join(clips_dir, f"scene_{sid:03d}.card.xfade.mp4")
                ext_frames = _scene_frame_count(scene) + half
                ext_scene = {
                    **scene,
                    "frames": ext_frames,
                    "duration": round(ext_frames / FPS, 3),
                }
                footage_overlays = [
                    o for o in overlays if o.get("kind") not in ("header", "counter")
                ]
                render_section_intro_clip(
                    ext_scene, src, out,
                    index=card["index"], title=card["title"],
                    item_noun=card.get("item_noun", ""),
                    # +half seconds to match the +half frames this seam adds: the
                    # fade-through-black is centred on the cut, so the card rises
                    # from black starting half a fade before the scene's nominal
                    # start and would otherwise END half a fade early, cutting to
                    # footage while the line is still spoken. Growing the card by
                    # the same half keeps footage_frames constant vs the plain
                    # path, so the card covers the full line (no footage tail).
                    card_seconds=card.get("card_seconds", card_seconds) + half / FPS,
                    card_comp=card.get("comp", card_comp),
                    card_props=card.get("props"),
                    transition=per_transition, ken_burns=per_ken_burns,
                    overlays=footage_overlays, edit_style=edit_style,
                    # Re-encode the joined card clip (not stream-copy): it is
                    # decoded again by the xfade/concat filters below, which drop
                    # frames off a concat-demuxer copy (see _concat_segments_copy).
                    reencode=True,
                )
            else:
                out = os.path.join(clips_dir, f"scene_{sid:03d}.xfade.mp4")
                render_extended_clip(
                    scene, src, out,
                    extra_frames=half,
                    transition=per_transition,
                    ken_burns=per_ken_burns,
                    overlays=overlays,
                    edit_style=edit_style,
                )
            input_paths[j] = out
        fa = _scene_frame_count(windows[i])
        seam_offsets[i] = (fa - half) / FPS

    # Render the two extended clips flanking each BLUR seam, mirroring the fade seam:
    # each is re-rendered +BLUR_DISSOLVE_FRAMES frames of REAL footage
    # (render_extended_clip) and its input slot is overridden with the extended path,
    # so the graph below can defocus-dissolve the pair over a centered 2N-frame
    # overlap at NORMAL SPEED and still emit exactly Fa+Fb frames — no slowdown, no
    # duplicated frames. A flanking clip too short to spare N frames each side is
    # skipped safely (that seam falls back to a hard cut, still Fa+Fb frames), so the
    # duration guard always holds. A blur seam never lands on a section-card clip (the
    # classifier keeps it non-adjacent to a fade), so its flanking clips are always
    # plain.
    n_blur = BLUR_DISSOLVE_FRAMES
    for i in list(blur_seams):
        fa = _scene_frame_count(windows[i])
        fb = _scene_frame_count(windows[i + 1])
        if fa <= n_blur or fb <= n_blur:
            print(
                f"  Blur-dissolve seam at clips {i}/{i + 1} skipped: a flanking "
                f"clip is <= {n_blur} frames (needs > {n_blur} to defocus-dissolve); "
                f"using a hard cut."
            )
            blur_seams.remove(i)
            continue
        print(
            f"  Rendering blur-dissolve seam: clips {i}->{i + 1} "
            f"(scenes {windows[i]['id']}->{windows[i + 1]['id']})..."
        )
        for j in (i, i + 1):
            scene = windows[j]
            sid = scene["id"]
            src = footage_paths.get(sid)
            if not src or not os.path.exists(src):
                raise FileNotFoundError(f"No footage for scene {sid}")
            entry = edl_by_id.get(sid, {})
            out = os.path.join(clips_dir, f"scene_{sid:03d}.blur.mp4")
            render_extended_clip(
                scene, src, out,
                extra_frames=n_blur,
                transition=entry.get("transition", transition),
                ken_burns=entry.get("ken_burns", ken_burns),
                overlays=entry.get("overlays", []),
                edit_style=edit_style,
            )
            input_paths[j] = out

    # Build the concat FILTER graph: normalize every input (the EXISTING shared
    # chain), then per seam either xfade the pair (fade) or defocus-dissolve the pair
    # (blur); concat the resulting streams.
    norm = _normalize_video_chain()
    n = len(input_paths)
    lines = [f"[{k}:v]{norm}[n{k}]" for k in range(n)]

    input_args: list[str] = []
    for p in input_paths:
        input_args += ["-i", os.path.abspath(p)]

    xfade_dur = SECTION_FADEBLACK_FRAMES / FPS
    fade_set = set(fade_seams)
    blur_set = set(blur_seams)

    # Blur-dissolve overlap params (mirrors the fade seam, minus the dip-to-black): a
    # CENTERED 2N-frame EASED cross-dissolve over the two extended flanking clips plus
    # a per-side ramped defocus. The eased opacity is the same inOutQuint curve the
    # /remotion blurDissolve used; xfade ``custom`` P runs 1->0, so ease (1-P) into a
    # 0->1 progress PE and blend A*(1-PE)+B*PE per plane — the SAME curve the defocus
    # ramp (_blur_dissolve_sendcmd) uses, so the softest, most-blended instant is
    # centered on the original cut.
    blur_overlap = 2 * n_blur
    blur_xfade_dur = blur_overlap / FPS
    blur_expr = (
        "st(1, 1-P); "
        "st(0, if(lt(ld(1),0.5), 16*pow(ld(1),5), 1-pow(-2*ld(1)+2,5)/2)); "
        "A*(1-ld(0))+B*ld(0)"
    )

    concat_labels: list[str] = []
    k = 0
    # Branch on the seam type: a ``fade_black`` pair blends via
    # ``xfade=transition=fadeblack`` (the picture dips THROUGH black at the cut); a
    # ``blur_dissolve`` pair defocus-dissolves over a centered 2N overlap (each side
    # ramped-blurred on its own timeline, then eased-crossfaded); every ``cut`` clip
    # passes through untouched.
    while k < n:
        if k in fade_set:
            lines.append(
                f"[n{k}][n{k + 1}]xfade=transition=fadeblack:"
                f"duration={xfade_dur:.3f}:offset={seam_offsets[k]:.3f}[x{k}]"
            )
            concat_labels.append(f"[x{k}]")
            k += 2
        elif k in blur_set:
            # A's overlap is its last 2N frames [Fa-N, Fa+N); B's is its first 2N
            # frames [0, 2N). The eased-xfade offset (Fa-N)/FPS centers the 2N overlap
            # on the original cut at frame Fa, so the pair still emits Fa+Fb frames.
            fa = _scene_frame_count(windows[k])
            a_start = fa - n_blur
            lines.append(
                f"[n{k}]sendcmd=c='"
                f"{_blur_dissolve_sendcmd(True, a_start, blur_overlap)}',"
                f"gblur=sigma=0.01:steps=3[ba{k}]"
            )
            lines.append(
                f"[n{k + 1}]sendcmd=c='"
                f"{_blur_dissolve_sendcmd(False, 0, blur_overlap)}',"
                f"gblur=sigma=0.01:steps=3[bb{k}]"
            )
            lines.append(
                f"[ba{k}][bb{k}]xfade=transition=custom:"
                f"duration={blur_xfade_dur:.4f}:offset={a_start / FPS:.4f}:"
                f"expr='{blur_expr}'[xb{k}]"
            )
            concat_labels.append(f"[xb{k}]")
            k += 2
        else:
            concat_labels.append(f"[n{k}]")
            k += 1
    n_concat = len(concat_labels)
    graph = (
        ";".join(lines) + ";"
        + "".join(concat_labels) + f"concat=n={n_concat}:v=1:a=0[outv]"
    )

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

    # Guard the duration-neutral invariant. Each blended pair emits exactly Fa+Fb
    # frames, so the crossfaded video must still hold the quantized total (sum of
    # per-scene frames == the audio/subtitle clock). The xfade/concat FILTER can
    # exit 0 yet silently drop frames on a malformed input (e.g. a concat-demuxer
    # copy whose DTS layout reads as early EOF — see _concat_segments_copy), so
    # verify here and fail loudly rather than ship a truncated, audio-desynced cut.
    expected_frames = sum(_scene_frame_count(s) for s in windows)
    actual_frames = _count_video_frames(silent_video)
    if actual_frames != expected_frames:
        raise RuntimeError(
            f"Section-crossfade concat for {project_name!r} produced "
            f"{actual_frames} frames but the scene timeline totals "
            f"{expected_frames} — a filter silently dropped frames. Refusing to "
            f"ship a truncated/desynced video."
        )

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

    section_cards: when True, place a section-header title card on every scene the
    EDL marks with a ``card`` (the section-intro scenes) — but only when the
    channel has a section-header DEFAULT design; otherwise the EDL carries no
    cards and this is a no-op plain render. Each card eats into THAT scene's own
    frames, so the total length — and therefore the audio + subtitle timelines —
    is unchanged. Karaoke cues that play entirely under a card are suppressed.
    False forces cards off (byte-identical to the plain path). card_seconds sets
    the card length; card_comp is a fallback comp (each card resolves its own from
    the channel default). output_name: filename inside video/, so a card render
    can write beside an untouched final.mp4.

    section_transitions: when True, route the concat through
    concat_clips_crossfade, which blends a short fade-to-black INTO every scene the
    EDL marks with a ``fade_black`` ``lead_in`` (the section starts + the
    conclusion) AND defocus-dissolves a mid-tier ``blur_dissolve`` at every
    within-segment scene the EDL marks with a ``blur_dissolve`` ``lead_in`` — both
    instead of a hard cut. Both are duration-neutral (each still emits Fa+Fb
    frames), so the audio + subtitle timelines are unchanged. Cards and fades
    COEXIST: a section start is BOTH a card-fronted clip AND the incoming side of a
    fade-to-black, so the previous section's footage fades to black and the header
    card rises FROM black. False forces every seam off (plain hard-cut concat)."""
    if transition not in ("cut", "fade"):
        raise ValueError(f"transition must be 'cut' or 'fade', got {transition!r}")

    # Cards are EDL-driven: build the map from the EDL's per-scene ``card``
    # fields (re-resolving each card's design from the channel's section-header
    # default). ``section_cards=False`` is the kill-switch — forces cards off.
    cards: dict[int, dict] = {}
    if section_cards:
        edl = _load_or_create_edl(
            project_name, transition=transition, ken_burns=ken_burns,
        )
        cards = _cards_from_edl(edl, _project_channel_id(project_name))
        # Per-card hold: keep each card up until its narrated line finishes (+ a
        # beat), replacing the fixed SECTION_CARD_SECONDS for cards. Stamped onto
        # each card dict so render_all_scene_clips / concat_clips_crossfade /
        # the subtitle blank-windows below all use the same per-scene value.
        if cards:
            secs = _card_seconds_by_scene(project_name, cards, card_seconds)
            for sid, c in cards.items():
                c["card_seconds"] = secs.get(sid, card_seconds)

    print("  Assembling audio...")
    audio = assemble_audio(project_name)

    print("  Rendering scene clips...")
    clips = render_all_scene_clips(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
        section_cards=cards or None, card_seconds=card_seconds, card_comp=card_comp,
    )

    print("  Concatenating clips...")
    if section_transitions:
        # Cards and fades coexist: the clips list already carries the card-fronted
        # section-intro clips (render_all_scene_clips), and concat_clips_crossfade
        # fades INTO them at each fade_black lead_in — a section start gets BOTH a
        # card AND a fade-to-black rising into it. With no fade_black lead_ins this
        # internally falls back to a plain concat.
        silent = concat_clips_crossfade(
            project_name, clips, footage_paths,
            transition=transition, ken_burns=ken_burns,
            section_cards=cards or None,
            card_seconds=card_seconds, card_comp=card_comp,
        )
    else:
        silent = concat_clips(project_name, clips)

    # Windows covered by a section card, so the subtitle builder can suppress any
    # karaoke cue that would otherwise render over a card. Each window is
    # [scene start_time, start_time + card_frames/FPS] using the SAME frame math
    # render_section_intro_clip uses (the PER-CARD card_seconds, capped at the
    # scene), so the window's right edge lands on the card→footage seam. Because
    # the card now holds through its whole narrated line, this suppresses that
    # line's subtitle entirely (the card carries it) while the NEXT scene's
    # narration — a new clip — keeps its subtitle. None when cards are off.
    blank_windows = None
    if cards:
        windows_by_id = {s["id"]: s for s in load_scene_windows(project_name)}
        blank_windows = []
        for sid in cards:
            s = windows_by_id[sid]
            scene_frames = _scene_frame_count(s)
            cs = cards[sid].get("card_seconds", card_seconds)
            card_frames = min(round(cs * FPS), scene_frames)
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
