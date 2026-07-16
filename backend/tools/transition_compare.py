#!/usr/bin/env python3
"""transition_compare.py -- reusable EASED xfade-dissolve comparison harness.

Why this exists
---------------
The committed pipeline crossfade (``assembly_service.concat_clips_crossfade``)
joins section seams with ``xfade=transition=fade`` -- a LINEAR cross-dissolve.
Linear is the "cheap tell": the blend rate is constant, so it reads as software
default rather than an intentional cut. We want code-driven, EASED dissolves,
with near-linear pushed to ~zero in finals. This tool is the tuning loop: it
renders short, labeled A-tail -> transition -> B-head clips (plus a filmstrip
across each seam) so the feel can be locked by rating BEFORE anything ships.

Each comparison clip = ~``tail``s of clip A, then the transition (``duration``s),
then ~``head``s of clip B  ==>  total ~= tail + head + duration (~2.8s default).
The eased dissolve is rendered via ``xfade=transition=custom:expr=...`` where the
outgoing->incoming blend runs on an EASED progress E(P). NOTE: in ffmpeg's xfade
``custom``, the expr variables A/B are NOT the naive "first/second input" -- the
form that reproduces ``transition=fade``'s outgoing->incoming direction is
``B*(1-P)+A*P`` (verified empirically against fade in this build; the naive
``A*(1-P)+B*P`` renders the dissolve time-reversed). So the eased pixel is
``B*(1-E) + A*E``; linear is E=P (identical to ``transition=fade``).

Everything is pure ffmpeg -- no generation, no LLM/TTS. Canvas matches the
pipeline (1920x1080, 25 fps, yuv420p, square pixels; see assembly_service
OUT_W/OUT_H/FPS + _normalize_video_chain).

How to run
----------
Built-in curated set (5 clips) + per-clip filmstrips + one contact sheet, using
the two default project clips, into /tmp/xfade::

    python backend/tools/transition_compare.py

Override the two input clips and/or the output dir::

    python backend/tools/transition_compare.py \
        --clip-a /path/A.mp4 --clip-b /path/B.mp4 --out-dir /tmp/xfade

Define your own comparison set (repeat --set; each is EASING:SECONDS)::

    python backend/tools/transition_compare.py \
        --set smoothstep:0.4 --set ease_in_out_cubic:0.5 --set linear:0.4

List the available easing curves (name -> eased-progress expr) and exit::

    python backend/tools/transition_compare.py --list-easings

Tune segment lengths / filmstrip density::

    python backend/tools/transition_compare.py --tail 1.0 --head 1.0 --frames 12

Add a new easing
----------------
Add one entry to EASINGS below: value is E(P), the eased progress written in
terms of xfade's ``P`` (ffmpeg eval syntax -- if/lt/gt/pow/... allowed; commas
are safe because the expr is wrapped in single quotes). That's the only change
needed; it becomes usable via ``--set <name>:<seconds>`` immediately.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

# --- Canvas: match the pipeline (assembly_service OUT_W/OUT_H/FPS + normalize) -
OUT_W, OUT_H, FPS = 1920, 1080, 25
NORMALIZE = (
    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
    f"crop={OUT_W}:{OUT_H},fps={FPS},format=yuv420p,setsar=1"
)

# --- Easing curves as EASED PROGRESS E(P), P = xfade progress in [0,1] ---------
# The dissolve blends B*(1-E) + A*E (see eased_blend: in ffmpeg xfade ``custom``
# that form reproduces transition=fade's outgoing->incoming direction). E=P is a
# LINEAR fade (== transition=fade, the pipeline default / the cheap tell).
# ``if``/``lt``/``pow`` are ffmpeg eval funcs; commas are safe inside expr='...'.
EASINGS: dict[str, str] = {
    # Hermite smoothstep. Gentle S-curve; flat shoulders, center slope 1.5.
    "smoothstep": "P*P*(3-2*P)",
    # Ease-in-out cubic. Steeper crossover (center slope 3), still flat shoulders.
    "ease_in_out_cubic": "if(lt(P,0.5),4*P*P*P,1-pow(-2*P+2,3)/2)",
    # Ease-in-out quartic -- the "snappier" curve (center slope 4). NOTE: a
    # symmetric, monotonic *cubic* tops out at center slope 3 (== ease_in_out_
    # cubic) unless you flatten it toward near-linear shoulders -- exactly the
    # tell we want gone -- so "snappier than cubic" is realized as this quartic
    # sibling (same flat-shoulder S shape, sharper mid-crossover).
    "ease_in_out_quart": "if(lt(P,0.5),8*P*P*P*P,1-pow(-2*P+2,4)/2)",
    # Reference ONLY. Linear == transition=fade the pipeline ships today; the
    # constant-rate look is the tell we're eliminating. Avoid in finals.
    "linear": "P",
}

# Burned-in label overrides (avoid ':' -- drawtext's option separator). Anything
# not listed derives "<easing> @ <dur>s".
LABEL_OVERRIDES: dict[str, str] = {
    "linear": "LINEAR - reference (avoid)",
}

# The curated default comparison set: (easing, duration_seconds). Not a grid --
# a handful that vary easing + duration meaningfully, plus one linear reference.
DEFAULT_SET: list[tuple[str, float]] = [
    ("smoothstep", 0.40),
    ("ease_in_out_cubic", 0.40),
    ("ease_in_out_cubic", 0.50),
    ("ease_in_out_quart", 0.35),
    ("linear", 0.40),
]

# Two visually distinct clips from the 7-flowers project: a tight, dark orange
# lily (scene_011) dissolving into a bright, wide plant nursery (scene_005). The
# large luminance / hue / composition gap makes the easing TIMING easy to judge.
_PROJECT = (
    Path.home()
    / "Documents/Aqua/projects/7-flowers-hummingbirds-physically-cannot-resist-2"
)
DEFAULT_CLIP_A = str(_PROJECT / "clips/scene_011.mp4")  # tail of A
DEFAULT_CLIP_B = str(_PROJECT / "clips/scene_005.mp4")  # head of B

# A real font so drawtext can render labels (fontconfig fallback if none found).
FONTFILE = next(
    (
        p
        for p in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        )
        if os.path.exists(p)
    ),
    None,
)


def eased_blend(easing: str) -> str:
    """The custom-xfade per-pixel expr for ``easing``: ``B*(1-E) + A*E``.

    Empirically (ffmpeg 8.x) xfade ``custom`` exposes A as the incoming (second)
    frame and B as the outgoing (first), the OPPOSITE of the naive reading:
    ``B*(1-P)+A*P`` reproduces ``transition=fade`` exactly, while ``A*(1-P)+B*P``
    renders the dissolve time-reversed. So the eased incoming fraction is E(P)."""
    e = EASINGS[easing]
    return f"B*(1-({e}))+A*({e})"


def transition_token(easing: str, dur: float, offset: float) -> str:
    """The exact ``xfade=...`` token used (single source of truth for the graph
    AND the printed summary). Linear uses the built-in ``fade`` -- byte-for-byte
    what the pipeline ships; every other easing uses a custom eased expr."""
    if easing == "linear":
        return f"xfade=transition=fade:duration={dur:.3f}:offset={offset:.3f}"
    return (
        f"xfade=transition=custom:expr='{eased_blend(easing)}':"
        f"duration={dur:.3f}:offset={offset:.3f}"
    )


def label_for(easing: str, dur: float) -> str:
    return LABEL_OVERRIDES.get(easing, f"{easing} @ {dur:.2f}s")


def _drawtext(label: str, fontsize: int, y_expr: str) -> str:
    """A drawtext filter drawing ``label`` bottom-left in a translucent box."""
    font = f"fontfile={FONTFILE}" if FONTFILE else "font=sans"
    return (
        f"drawtext={font}:text='{label}':x=28:y={y_expr}:"
        f"fontsize={fontsize}:fontcolor=white:box=1:boxcolor=black@0.6:"
        f"boxborderw=14"
    )


def _run(cmd: list[str], what: str) -> None:
    """Run ffmpeg, surfacing stderr on failure (mirrors assembly_service)."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(f"ffmpeg failed ({what}):\n{stderr}") from e


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def render_clip(
    clip_a: str, clip_b: str, easing: str, dur: float, tail: float, head: float,
    out_path: str, a_start: float | None = None, b_start: float | None = None,
) -> str:
    """Render one comparison clip and return the exact transition token used.

    Layout: ~``tail``s of A alone, the ``dur``s transition, ~``head``s of B alone.
    A's segment is its TAIL (last tail+dur seconds); B's is its HEAD.
    """
    la, lb = tail + dur, head + dur
    dur_a, dur_b = probe_duration(clip_a), probe_duration(clip_b)
    if la > dur_a + 1e-3 or lb > dur_b + 1e-3:
        raise ValueError(
            f"Need {la:.2f}s of A ({dur_a:.2f}s) and {lb:.2f}s of B "
            f"({dur_b:.2f}s) -- reduce --tail/--head or pick longer clips."
        )
    if a_start is None:
        a_start = max(0.0, dur_a - la)  # tail of A
    if b_start is None:
        b_start = 0.0                   # head of B
    offset = tail                       # == la - dur: pure A for `tail` seconds
    token = transition_token(easing, dur, offset)
    label = _drawtext(label_for(easing, dur), fontsize=44, y_expr="h-th-28")
    graph = (
        f"[0:v]{NORMALIZE}[a];[1:v]{NORMALIZE}[b];"
        f"[a][b]{token}[x];[x]{label}[out]"
    )
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{a_start:.3f}", "-t", f"{la:.3f}", "-i", clip_a,
            "-ss", f"{b_start:.3f}", "-t", f"{lb:.3f}", "-i", clip_b,
            "-filter_complex", graph,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            out_path,
        ],
        what=f"render {os.path.basename(out_path)}",
    )
    return token


def render_filmstrip(
    clip_path: str, out_path: str, tail: float, dur: float, label: str,
    frames_dir: str, n: int = 10, tile_w: int = 300,
) -> None:
    """A horizontal strip of ``n`` frames sampled evenly across the seam window
    [tail-0.12 .. tail+dur+0.12], so the blend's motion is visible at a glance.
    Frames are pulled one-by-one (frame-accurate output seek) then tiled."""
    t0 = max(0.0, tail - 0.12)
    t1 = tail + dur + 0.12
    stem = Path(out_path).stem
    frame_paths = []
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        fp = os.path.join(frames_dir, f"{stem}_{i:02d}.png")
        _run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", clip_path, "-ss", f"{t:.3f}", "-frames:v", "1",
                "-vf", f"scale={tile_w}:-1", fp,
            ],
            what=f"filmstrip frame {i} of {stem}",
        )
        frame_paths.append(fp)
    # Tile the n frames into one row, then caption the strip.
    strip_label = _drawtext(label, fontsize=26, y_expr="h-th-14")
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", os.path.join(frames_dir, f"{stem}_%02d.png"),
            "-frames:v", "1",
            "-vf", f"tile={n}x1,{strip_label}",
            out_path,
        ],
        what=f"tile filmstrip {stem}",
    )
    for fp in frame_paths:
        try:
            os.remove(fp)
        except OSError:
            pass


def build_contact_sheet(strip_paths: list[str], out_path: str) -> None:
    """Stack the per-clip filmstrips vertically for one-glance comparison."""
    inputs = []
    for p in strip_paths:
        inputs += ["-i", p]
    graph = "".join(f"[{i}:v]" for i in range(len(strip_paths)))
    graph += f"vstack=inputs={len(strip_paths)}"
    _run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, out_path],
        what="contact sheet",
    )


def parse_set(items: list[str]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for it in items:
        if ":" not in it:
            raise SystemExit(f"--set expects EASING:SECONDS, got {it!r}")
        name, _, secs = it.partition(":")
        if name not in EASINGS:
            raise SystemExit(
                f"unknown easing {name!r}; choose from {', '.join(EASINGS)}"
            )
        out.append((name, float(secs)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render eased xfade-dissolve comparison clips + filmstrips."
    )
    ap.add_argument("--clip-a", default=DEFAULT_CLIP_A, help="input A (tail used)")
    ap.add_argument("--clip-b", default=DEFAULT_CLIP_B, help="input B (head used)")
    ap.add_argument("--out-dir", default="/tmp/xfade")
    ap.add_argument("--tail", type=float, default=1.2, help="seconds of A alone")
    ap.add_argument("--head", type=float, default=1.2, help="seconds of B alone")
    ap.add_argument("--frames", type=int, default=10, help="frames per filmstrip")
    ap.add_argument("--a-start", type=float, default=None, help="override A cut-in")
    ap.add_argument("--b-start", type=float, default=None, help="override B cut-in")
    ap.add_argument(
        "--set", action="append", dest="sets", default=None,
        help="EASING:SECONDS (repeatable); omit for the curated default set",
    )
    ap.add_argument("--list-easings", action="store_true")
    args = ap.parse_args()

    if args.list_easings:
        print("Easing curves (name -> eased progress E(P); eased dissolve expr is")
        print("B*(1-E)+A*E -- the form matching transition=fade in ffmpeg xfade custom):")
        for name, expr in EASINGS.items():
            tag = "  [reference/linear]" if name == "linear" else ""
            print(f"  {name:20s} {expr}{tag}")
        return

    comparison = parse_set(args.sets) if args.sets else DEFAULT_SET
    out_dir = os.path.abspath(args.out_dir)
    frames_dir = os.path.join(out_dir, "_frames")
    os.makedirs(frames_dir, exist_ok=True)

    print(f"clip A (tail): {args.clip_a}")
    print(f"clip B (head): {args.clip_b}")
    print(f"out dir      : {out_dir}\n")

    summary: list[tuple[str, str, str, str]] = []  # clip, strip, label, token
    strip_paths: list[str] = []
    for i, (easing, dur) in enumerate(comparison, start=1):
        stem = f"{i:02d}_{easing}_{int(round(dur * 1000))}ms"
        clip_out = os.path.join(out_dir, f"{stem}.mp4")
        strip_out = os.path.join(out_dir, f"{stem}.strip.png")
        token = render_clip(
            args.clip_a, args.clip_b, easing, dur, args.tail, args.head,
            clip_out, a_start=args.a_start, b_start=args.b_start,
        )
        render_filmstrip(
            clip_out, strip_out, args.tail, dur, label_for(easing, dur),
            frames_dir, n=args.frames,
        )
        strip_paths.append(strip_out)
        summary.append((clip_out, strip_out, label_for(easing, dur), token))
        print(f"[{i}] {label_for(easing, dur)}")
        print(f"    clip : {clip_out}")
        print(f"    strip: {strip_out}")
        print(f"    xfade: {token}\n")

    contact = os.path.join(out_dir, "_contactsheet.png")
    build_contact_sheet(strip_paths, contact)
    try:
        os.rmdir(frames_dir)
    except OSError:
        pass
    print(f"contact sheet: {contact}")


if __name__ == "__main__":
    main()
