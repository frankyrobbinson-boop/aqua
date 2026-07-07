/**
 * Atmosphere — ambient, deterministic "you're inside a moment" life layered over
 * GardenBloom: soft drifting warm SUNLIGHT pools + a scatter of floating
 * POLLEN/DUST motes. Pure frame-based motion (Math.sin/Math.cos keyed off the
 * current frame; NO Math.random / Date.now — every position + phase is derived
 * from the element index), so the <Player> preview and the MP4 render stay in
 * lockstep. Colors lean warm (soft gold/cream) and opacities stay LOW so the
 * title stays clearly readable.
 *
 * This file only DRAWS the two ambient layers plus their own gentle internal
 * drift. GardenBloom places them at fixed depths (light behind the foliage,
 * motes near the foreground) and fades them up from black WITH the scene (an
 * optional `enter` opacity) — there is no camera; nothing here needs the palette.
 *
 * Two exports so the card can place them at DIFFERENT depths:
 *   - `AtmosphereLight` — the dappled sun pools (far, behind the botanicals)
 *   - `AtmosphereMotes` — the floating motes (near, in front of the botanicals)
 */
import { useCurrentFrame, useVideoConfig } from "remotion";

// Warm sunlight tint (soft gold/cream), as an "r, g, b" fragment so opacity can
// be varied per layer via rgba().
const SUN_RGB = "255, 236, 201";
// Warm cream-gold — a touch deeper than white so the motes actually register as
// soft specks against the light garden wash (pure white would vanish on it).
const MOTE_RGB = "252, 231, 183";

// --- dappled sunlight -------------------------------------------------------

type Glow = {
  x: number; // % — center
  y: number; // %
  size: number; // px — diameter of the soft pool
  opacity: number; // peak alpha (kept low)
  driftX: number; // px — lateral drift amplitude
  driftY: number; // px — vertical drift amplitude
  freq: number; // cycles/sec — very slow
  phase: number; // rad — offset so the two pools don't move in unison
};

// One or two large, very soft warm pools that slowly slide across the scene like
// sun filtering through leaves. Placed off the dense left-center headline so the
// text stays clear. Deterministic (index-derived phases; sin/cos drift only).
const GLOWS: readonly Glow[] = [
  { x: 72, y: 24, size: 1180, opacity: 0.23, driftX: 64, driftY: 34, freq: 0.05, phase: 0.0 },
  { x: 33, y: 82, size: 1000, opacity: 0.16, driftX: -72, driftY: 40, freq: 0.042, phase: 1.7 },
];

export function AtmosphereLight({ enter = 1 }: { enter?: number }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
        opacity: enter,
      }}
    >
      {GLOWS.map((g, i) => {
        const w = t * g.freq * Math.PI * 2 + g.phase;
        const dx = Math.sin(w) * g.driftX;
        const dy = Math.cos(w) * g.driftY;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${g.x}%`,
              top: `${g.y}%`,
              width: g.size,
              height: g.size,
              marginLeft: -g.size / 2,
              marginTop: -g.size / 2,
              transform: `translate(${dx}px, ${dy}px)`,
              background: `radial-gradient(circle, rgba(${SUN_RGB}, ${g.opacity}) 0%, rgba(${SUN_RGB}, ${
                g.opacity * 0.45
              }) 32%, rgba(${SUN_RGB}, 0) 68%)`,
              filter: "blur(24px)",
            }}
          />
        );
      })}
    </div>
  );
}

// --- floating motes ---------------------------------------------------------

const MOTE_COUNT = 12;
// Golden-ratio increment — spreads the motes evenly across the frame from their
// index alone (a deterministic, low-discrepancy scatter, no Math.random).
const GOLDEN = 0.618033988749895;
const TAU = Math.PI * 2;

export function AtmosphereMotes({ enter = 1 }: { enter?: number }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
        opacity: enter,
      }}
    >
      {Array.from({ length: MOTE_COUNT }).map((_, i) => {
        // Deterministic scatter + phase, all derived from the index.
        const baseX = (i * GOLDEN * 100) % 100; // 0..100 %
        const baseY = (i * GOLDEN * 137 + 11) % 100; // 0..100 %
        const phase = (i * 1.7) % TAU;
        // A few motes read as CLOSER: larger, softer, a touch brighter.
        const near = i % 4 === 0;
        const size = near ? 12 + (i % 3) * 3 : 5 + (i % 3) * 1.5;
        const ampX = near ? 46 : 30; // px — lateral sway
        const ampY = near ? 34 : 24; // px — vertical bob
        const fx = 0.05 + (i % 5) * 0.006; // cycles/sec — slow, varied
        const fy = 0.04 + (i % 4) * 0.006;
        const rise = (near ? 7 : 5) * t; // gentle net upward drift (px)

        const dx = Math.sin(t * fx * TAU + phase) * ampX;
        const dy = Math.sin(t * fy * TAU + phase * 1.3) * ampY - rise;
        // Soft twinkle so the motes feel alive / catch the light.
        const twinkle = 0.62 + 0.38 * Math.sin(t * (0.3 + (i % 3) * 0.08) * TAU + phase);
        const opacity = (near ? 0.42 : 0.26) * twinkle;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${baseX}%`,
              top: `${baseY}%`,
              width: size,
              height: size,
              marginLeft: -size / 2,
              marginTop: -size / 2,
              borderRadius: "50%",
              transform: `translate(${dx}px, ${dy}px)`,
              background: `radial-gradient(circle, rgba(${MOTE_RGB}, ${opacity}) 0%, rgba(${MOTE_RGB}, ${
                opacity * 0.55
              }) 45%, rgba(${MOTE_RGB}, 0) 72%)`,
              filter: `blur(${near ? 2 : 1}px)`,
            }}
          />
        );
      })}
    </div>
  );
}
