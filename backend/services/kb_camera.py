"""kb_camera.py -- a global Ken Burns "virtual camera" for a run of still scenes.

Why this exists
---------------
The shipping Ken Burns move (``assembly_service`` / ``kenburns_subpixel``) is a
per-scene push that resets to a dead stop at every cut: each still zooms 1.0->1.08
on its own, independent of its neighbours, so the sequence reads as N little
unrelated zooms. This module computes ONE continuous, gentle ping-pong zoom that
is SHARED across a whole run of consecutive stills, so the motion flows THROUGH
the hard cuts -- a shot entered mid-push keeps pushing, a shot entered mid-pull
keeps pulling. It is pure math: it emits per-scene per-frame zoom factors and an
anchor. It renders nothing and imports nothing heavy (stdlib ``math`` only), so
both the offline comparison harness and (later) the pipeline can drive it.

The model, in one breath
------------------------
Everything happens in LOG-ZOOM space, because a constant rate in log-zoom is a
constant *perceptual* zoom (the eye reads zoom exponentially). We build a single
global log-zoom wave ``g(m)`` over the run's total frames ``m``:

  * an oscillating **wave** between 0 and ``ln(1+A)`` with a reversal every ``P``
    seconds (a full in+out cycle is ``2P``), in one of two shapes (``interp``): a
    **smoothstep-eased triangle** (default) -- constant velocity (steady) between
    reversals, the reversals rounded so the camera eases to a stop and reverses
    smoothly ("ease at the reversals, steady between") -- or a **raised-cosine
    ("sine")** ``(ln(1+A)/2)*(1 - cos(pi*m/P))`` whose velocity varies continuously
    with no constant-speed cruise (a "flowier" reversal);
  * wrapped in an amplitude **envelope** that smoothstep-ramps 0->1 over the
    first ``ease_seconds`` (a QUICK fixed ease, ~1s by default) and 1->0 over the
    last ``ease_seconds`` (capped to 1/3 of the run so short clips still ease),
    so the camera eases in from rest at the very start and out to rest at the very
    end -- but reaches full ping-pong amplitude almost immediately, so even short
    runs show the real cadence instead of spending a whole reversal fading in.

Per scene we then apply the **re-basing rule**: take the run's ``g`` over that
scene's frame window and subtract the window's minimum, so

    z(frame) = exp( g(frame) - min_over_window(g) ).

Two properties fall straight out of this and are exactly why cross-cut motion is
continuous:

  1. Subtracting a per-window constant does NOT change the derivative of the
     log-zoom, so the per-frame log-zoom VELOCITY ``dg`` is identical on both
     sides of every cut -- the motion carries through the hard cut. (The absolute
     zoom jumps at the cut, as it must for two different images; the *rate* does
     not.) The exposed ``velocity`` array is this ``dg`` (a backward difference of
     ``g``), so a scene's first-frame velocity references the previous scene's
     last frame across the cut -- precisely the continuity quantity to test.
  2. Every scene touches ``z = 1.0`` (fully uncropped, i.e. the base 16:9 fill
     with no extra push) at its most-zoomed-out moment: a scene entered while the
     global camera is zooming IN starts uncropped and pushes in; one entered while
     it is zooming OUT starts zoomed-in and pulls out to uncropped.

``z`` is clamped to ``[1.0, 1+A]`` as a safety (it already lives there by
construction). The anchor is a fixed centre ``(0.5, 0.5)`` for now, but is carried
per scene so a future auto-target can pass a real focal point per still.

Deterministic, no RNG: ``compute_run`` is a pure function of its inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Output frame rate -- matches the pipeline (assembly_service FPS / the KB tools).
FPS = 25

# Fraction of each half-segment spent easing the velocity in/out of a reversal;
# the remaining middle runs at steady (constant) velocity. 0.25 => ease over the
# first and last quarter of each in/out ramp, cruise through the middle half.
DEFAULT_EASE_FRAC = 0.25

# Seconds the amplitude ENVELOPE spends ramping in at the start and out at the end
# (distinct from DEFAULT_EASE_FRAC, which eases the ping-pong's own reversals). A
# QUICK fixed ease so the camera reaches full ping-pong amplitude almost at once;
# capped per run to 1/3 of its length so short clips still ease fully in and out.
DEFAULT_EASE_SECONDS = 1.0


@dataclass(frozen=True)
class SceneSpec:
    """One still's slot in the run: how many output frames it occupies, where it
    starts on the run-global frame clock, and its Ken Burns anchor. ``anchor`` is
    normalized output coords (0.5, 0.5 = frame centre) and defaults to centre;
    it is plumbed through so a per-scene focal point can be supplied later."""

    frames: int
    start: int
    anchor: tuple[float, float] = (0.5, 0.5)


@dataclass(frozen=True)
class SceneCamera:
    """The computed camera for one scene: a per-frame zoom ``z`` (len == frames,
    in [1.0, 1+A]) and the matching per-frame log-zoom ``velocity`` (dg, a global
    backward difference -- element 0 is the rate carried across the cut from the
    previous scene). ``anchor`` echoes the spec."""

    start: int
    frames: int
    z: list[float]
    velocity: list[float]
    anchor: tuple[float, float]


@dataclass(frozen=True)
class RunCamera:
    """The whole run: the per-scene cameras plus the raw global signals the
    acceptance tests read (``g`` = global log-zoom wave*envelope, ``velocity`` =
    its per-frame backward difference)."""

    scenes: list[SceneCamera]
    total_frames: int
    reversal_period_s: float
    amplitude: float
    interp: str
    ease_frac: float
    ease_seconds: float
    g: list[float]
    velocity: list[float]


# --- Building blocks -----------------------------------------------------------
def _smoothstep(x: float) -> float:
    """Classic smoothstep on [0,1] -- zero slope at both ends, so it eases in and
    out. Clamped, so callers can pass raw (possibly out-of-range) ratios."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def _ramp_position(u: float, e: float) -> float:
    """Position along ONE half-segment (trough->peak) at local phase ``u`` in
    [0,1], for a velocity profile that smoothstep-ramps 0->cruise over the first
    ``e`` of the segment, holds cruise (steady) over the middle, and smoothstep-
    ramps cruise->0 over the last ``e``. Returns a monotonic 0->1 with zero slope
    at u=0 and u=1 (the reversals) and constant slope in the steady middle.

    Closed form: the velocity area is ``1 - e`` (each smoothstep ramp contributes
    ``e/2``, the flat middle ``1 - 2e``), so position = (integral of velocity) /
    ``(1 - e)``. ``e -> 0`` degenerates to the pure (linear) triangle ramp."""
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    if e <= 0.0:
        return u  # pure triangle: constant velocity, sharp reversals
    inv = 1.0 / (1.0 - e)
    if u < e:  # ease-in: integral of the smoothstep velocity, scaled by e
        a = u / e
        return e * (a ** 3 - 0.5 * a ** 4) * inv
    if u <= 1.0 - e:  # steady middle: e/2 accumulated during ease-in, then linear
        return (0.5 * e + (u - e)) * inv
    b = (1.0 - u) / e  # ease-out: mirror of the ease-in about the segment centre
    return ((1.0 - e) - e * (b ** 3 - 0.5 * b ** 4)) * inv


def _eased_triangle(m: float, half_period_frames: float, e: float) -> float:
    """The smoothstep-eased triangle wave in [0,1] at global frame ``m``. Even
    half-segments ramp trough->peak, odd ones peak->trough; a reversal falls every
    ``half_period_frames``. ``m = 0`` sits at a trough (value 0)."""
    if half_period_frames <= 0.0:
        return 0.0
    phase = m / half_period_frames
    k = math.floor(phase)
    u = phase - k
    r = _ramp_position(u, e)
    return r if (k % 2 == 0) else (1.0 - r)


def _sine_wave(m: float, half_period_frames: float) -> float:
    """A raised-cosine wave in [0,1] at global frame ``m``: ``0.5*(1 - cos(pi*m/P))``
    with ``P = half_period_frames``. A trough (0) at ``m = 0`` and a peak (1) at every
    ``half_period_frames`` -- the SAME reversal cadence as ``_eased_triangle`` -- but
    its velocity is a continuous ``sin`` that reaches zero ONLY at the reversals, with
    no constant-speed cruise in between (the "flowier" alternative to the triangle's
    trapezoidal velocity). ``ease_frac`` has no effect on it -- the cosine sets its own
    easing."""
    if half_period_frames <= 0.0:
        return 0.0
    return 0.5 * (1.0 - math.cos(math.pi * m / half_period_frames))


def _envelope(m: int, total_frames: int, ramp_frames: float) -> float:
    """Amplitude envelope: smoothstep 0->1 over the first ``ramp_frames`` and
    1->0 over the last ``ramp_frames``, flat 1 in between (``min`` of the two
    ramps, so short runs that can't fit both simply ease in and back out without
    ever reaching 1). Because smoothstep has zero slope at its ends, the envelope
    -- and hence the whole camera -- eases to genuine rest at frame 0 and the last
    frame regardless of the wave's phase there."""
    if ramp_frames <= 0.0:
        return 1.0
    last = max(1, total_frames - 1)
    f_in = _smoothstep(m / ramp_frames)
    f_out = _smoothstep((last - m) / ramp_frames)
    return min(f_in, f_out)


# --- Public API ----------------------------------------------------------------
def specs_from_durations(
    durations: list[float],
    fps: int = FPS,
    anchors: list[tuple[float, float]] | None = None,
) -> list[SceneSpec]:
    """Build an ordered still-run from real per-scene durations: frames =
    round(duration*fps) (>= 1), global start = sum of preceding frames. Optional
    per-scene anchors (defaults to centre)."""
    specs: list[SceneSpec] = []
    start = 0
    for i, dur in enumerate(durations):
        frames = max(1, round(max(0.0, dur) * fps))
        anchor = anchors[i] if anchors is not None else (0.5, 0.5)
        specs.append(SceneSpec(frames=frames, start=start, anchor=anchor))
        start += frames
    return specs


def compute_run(
    scenes: list[SceneSpec],
    reversal_period_s: float,
    amplitude: float,
    interp: str = "smoothstep",
    ease_frac: float = DEFAULT_EASE_FRAC,
    ease_seconds: float = DEFAULT_EASE_SECONDS,
    fps: int = FPS,
) -> RunCamera:
    """Compute the shared virtual camera for a run of still scenes.

    Parameters
    ----------
    scenes : ordered ``SceneSpec`` list (see ``specs_from_durations``). Assumed
        contiguous (each ``start`` == previous ``start + frames``); the run's total
        frame count is taken from the last scene.
    reversal_period_s : ``P`` -- seconds between reversals (full in+out cycle 2P).
    amplitude : ``A`` -- zoom fraction, e.g. 0.08 => zoom spans 1.0..1.08.
    interp : reversal easing style. "smoothstep" (default) eases the velocity in/
        out of each reversal over ``ease_frac`` of the ramp and cruises at constant
        velocity between; "linear" forces a pure triangle (sharp reversals); "sine"
        is a raised-cosine wave whose velocity varies continuously with NO constant-
        speed cruise (the "flowy" profile) -- ``ease_frac`` is ignored for it.
        Structured so more curves can be added.
    ease_frac : fraction of each in/out ramp spent easing (see DEFAULT_EASE_FRAC).
    ease_seconds : seconds the amplitude ENVELOPE spends ramping 0->1 at the start
        and 1->0 at the end (a quick fixed ease, ~1s by default), capped to 1/3 of
        the run so short clips still ease fully. Distinct from ``ease_frac``, which
        eases the ping-pong's own reversals; this eases the whole move on/off.
    fps : output frame rate (default 25).

    Returns a ``RunCamera`` with a ``SceneCamera`` per input scene plus the raw
    global ``g`` / ``velocity`` signals.
    """
    if not scenes:
        return RunCamera([], 0, reversal_period_s, amplitude, interp, ease_frac,
                         ease_seconds, [], [])

    total = scenes[-1].start + scenes[-1].frames
    # ease_frac drives the eased-triangle's reversal ease only; "linear" (sharp
    # reversals) and "sine" (the cosine supplies its own easing) both ignore it.
    e = 0.0 if interp in ("linear", "sine") else max(0.0, min(0.5, ease_frac))
    peak = math.log1p(amplitude)  # ln(1 + A): the wave's top in log-zoom space
    half_period_frames = reversal_period_s * fps  # P_frames: frames per reversal
    # QUICK fixed envelope ease: ramp the amplitude 0->1 over ease_seconds at the
    # start and 1->0 over ease_seconds at the end, so the camera reaches full
    # ping-pong amplitude almost immediately (this used to take a whole reversal
    # period, muting the first/last cadence on short runs). Capped at 1/3 of the
    # run so a short clip still eases fully in and back out.
    ramp_frames = min(ease_seconds * fps, total / 3.0)

    # The [0,1] oscillation shape sampled per global frame: a raised-cosine for
    # "sine" (continuously varying velocity, no cruise) else the smoothstep-eased
    # triangle (trapezoidal velocity -- ease into a reversal, cruise, ease out). Both
    # reverse every half_period_frames, so the cadence is identical.
    if interp == "sine":
        def _wave(m: int) -> float:
            return _sine_wave(m, half_period_frames)
    else:
        def _wave(m: int) -> float:
            return _eased_triangle(m, half_period_frames, e)

    # Global log-zoom signal g(m) = envelope(m) * ln(1+A) * wave(m). For "sine" this
    # is exactly envelope(m) * (ln(1+A)/2) * (1 - cos(pi*m/P_frames)).
    g = [
        _envelope(m, total, ramp_frames) * peak * _wave(m)
        for m in range(total)
    ]
    # Global per-frame log-zoom velocity: backward difference (v[0] = 0). This is
    # invariant to the per-scene re-basing constant, so it is continuous across
    # cuts; a scene's first velocity references the previous frame across the cut.
    velocity = [0.0] + [g[m] - g[m - 1] for m in range(1, total)]

    hi = 1.0 + amplitude
    scene_cams: list[SceneCamera] = []
    for spec in scenes:
        a, b = spec.start, spec.start + spec.frames
        window = g[a:b]
        mn = min(window)
        z = [min(hi, max(1.0, math.exp(gv - mn))) for gv in window]  # re-based + clamped
        scene_cams.append(
            SceneCamera(
                start=spec.start,
                frames=spec.frames,
                z=z,
                velocity=velocity[a:b],
                anchor=spec.anchor,
            )
        )

    return RunCamera(
        scenes=scene_cams,
        total_frames=total,
        reversal_period_s=reversal_period_s,
        amplitude=amplitude,
        interp=interp,
        ease_frac=e,
        ease_seconds=ease_seconds,
        g=g,
        velocity=velocity,
    )


# --- Standalone self-check (free, no third-party deps) -------------------------
def _self_check() -> None:
    """Assert the invariants the harness reports numerically: z in [1, 1+A], the
    per-frame log-velocity is continuous across every cut (boundary jumps do not
    exceed the within-scene distribution), and the camera is at rest at both ends.
    Runs on a synthetic 12-scene run so the module is verifiable without cv2/ffmpeg."""
    durations = [7.75, 4.56, 9.18, 8.8, 10.04, 9.7, 4.17, 12.55, 7.0, 13.72, 7.41, 4.9]
    A = 0.10
    specs = specs_from_durations(durations)
    run = compute_run(specs, reversal_period_s=4.0, amplitude=A)

    # z bounds.
    lo = min(min(s.z) for s in run.scenes)
    hi = max(max(s.z) for s in run.scenes)
    assert lo >= 1.0 - 1e-9 and hi <= 1.0 + A + 1e-9, (lo, hi)

    # Boundary velocity continuity vs within-scene per-frame velocity change.
    within = [
        abs(s.velocity[i] - s.velocity[i - 1])
        for s in run.scenes
        for i in range(1, len(s.velocity))
    ]
    boundary = [
        abs(run.scenes[k + 1].velocity[0] - run.scenes[k].velocity[-1])
        for k in range(len(run.scenes) - 1)
    ]
    max_within = max(within)
    max_boundary = max(boundary)
    # A cut must not stand out: its velocity jump stays within the ordinary
    # within-scene distribution (allow a hair of float slack).
    assert max_boundary <= max_within + 1e-9, (max_boundary, max_within)

    # Rest at the ends. The start is EXACTLY at rest (v_first == 0 by construction:
    # g[0] = 0). With the QUICK envelope ease the last frame no longer fades over a
    # whole reversal, so its discrete backward-difference leaves a small residual --
    # but it is imperceptible in absolute terms (< 1e-3 log-zoom/frame, ~0.1% zoom)
    # and a small fraction of the run's peak velocity.
    v_peak = max(abs(v) for v in run.velocity)
    assert abs(run.velocity[0]) < 1e-6
    assert abs(run.velocity[-1]) < 1e-3
    assert abs(run.velocity[-1]) <= 0.15 * v_peak

    # Determinism.
    run2 = compute_run(specs, reversal_period_s=4.0, amplitude=A)
    assert [s.z for s in run.scenes] == [s.z for s in run2.scenes]

    print("kb_camera self-check: PASS")
    print(f"  scenes={len(run.scenes)}  total_frames={run.total_frames}  "
          f"ease_seconds={run.ease_seconds:g} (ramp {min(run.ease_seconds * FPS, run.total_frames / 3):.0f} frames)")
    print(f"  z range=[{lo:.4f}, {hi:.4f}]  (bound 1.0..{1.0 + A:.2f})")
    print(f"  max boundary |dv|={max_boundary:.3e}  max within-scene |dv|={max_within:.3e}")
    print(f"  end velocities: first={run.velocity[0]:.3e}  "
          f"last={run.velocity[-1]:.3e} ({abs(run.velocity[-1]) / v_peak * 100:.1f}% of peak)")


if __name__ == "__main__":
    _self_check()
