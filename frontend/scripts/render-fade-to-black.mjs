/**
 * Batch renderer for the FADE-TO-BLACK rating clips — ROUND 4 (a true 3-phase
 * dip: fade A→black, DWELL on pure black, fade black→B).
 *
 * Round-3 verdict: the old fade-to-black "sped through the black" — an
 * @remotion/transitions Transition OVERLAPS the two clips, so the through-black
 * moment is a single midpoint frame with no dwell. Round 4 reworks fadeToBlack in
 * FootageTransition.tsx as a CUSTOM sequence structure (clip A holds → eased veil
 * 0→1 onto black → PURE-BLACK hold → eased veil 1→0 as clip B plays under it), so
 * the black hold is REAL extra time in the middle. This driver renders three
 * out/hold/in timings over two REAL clips and MARKS the moment with a longer,
 * lingering black.
 *
 * Measured off the user's `fade black.mov` reference (@30fps): ~0.40s fade-out,
 * ~0.20s dwell on near-black, ~0.25s fade-in (~0.85s total). The three variants
 * are the ref-match plus two progressively LONGER holds (the user wants it to
 * linger). Each carries its own fadeOut/blackHold/fadeIn (frames @30fps) and a
 * burned-in corner label reading the out / black / in timing.
 *
 * After each clip it cuts a LUMA FILMSTRIP — a fixed count of frames sampled
 * across the fade-out → dwell → fade-in span, tiled left→right, so the run of
 * pure-black tiles in the middle makes the DWELL visible (and countable). It then
 * stacks the per-clip strips into one contact sheet (ffmpeg). Every clip is
 * 1920x1080/30fps H.264.
 *
 * fadeToBlack is a Tier-A CSS dip (no WebGL, no motion blur), so this renders at
 * Remotion's default concurrency; the gl:angle backend mirrors render-remotion.mjs
 * only for parity.
 *
 * Usage (all optional; sensible 7-flowers defaults):
 *   node scripts/render-fade-to-black.mjs \
 *     [--clipA=/abs/a.mp4] [--clipB=/abs/b.mp4] [--out-dir=/tmp/xfade4] \
 *     [--easing=inOutQuint] [--holdFrames=36] [--trimA=0] [--trimB=0] \
 *     [--fadeOut=N] [--blackHold=N] [--fadeIn=N]
 *
 * `--fadeOut` / `--blackHold` / `--fadeIn`, when passed, OVERRIDE that phase on
 * EVERY variant (dial in / sweep ONE timing); otherwise each variant keeps its own
 * round-4 phase lengths. `--easing` overrides the veil-ramp curve on every variant
 * (any id in FootageTransition's EASINGS — e.g. inOutQuint / inOutCubic / strongBezier).
 * For a bespoke SET, edit the VARIANTS array below.
 *
 * To render ONE arbitrary fade-to-black instead, stage a clip under
 * frontend/public/ (the renderer serves public/ over http, it can't read file://)
 * and use the single-comp path with a staticFile() path:
 *   node scripts/render-remotion.mjs --comp=FootageTransition \
 *     --props='{"type":"fadeToBlack","params":{},
 *              "clipA":"xtrans-src/a.mp4","clipB":"xtrans-src/b.mp4",
 *              "trimA":0,"trimB":0,"holdFrames":36,"easing":"inOutQuint",
 *              "fadeOutFrames":12,"blackHoldFrames":6,"fadeInFrames":8,
 *              "label":"fade-to-black | out 0.40s / black 0.20s / in 0.27s (0.87s)"}' \
 *     --out=/tmp/xfade4/custom.mp4
 */
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { bundle } from "@remotion/bundler";
import {
  ensureBrowser,
  renderMedia,
  selectComposition,
} from "@remotion/renderer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Same GL backend as render-remotion.mjs — not needed for a Tier-A CSS dip, kept
// only for parity with the other headless render paths.
const CHROMIUM_OPTIONS = { gl: "angle" };

// Composition fps (mirror of src/remotion/constants.ts FPS) — converts phase
// frame counts to the seconds shown on the label + places the filmstrip window.
const FPS = 30;

// Per-frame render/delayRender budget. A pure CSS dip is cheap, but give each
// frame a generous budget so an OffthreadVideo proxy fetch under contention never
// trips a spurious timeout.
const RENDER_TIMEOUT_MS = 120000;

// Default veil-ramp curve id (resolved by FootageTransition's EASINGS). A strong
// ease-in-out so the veil DECELERATES onto black and eases back off it.
const DEFAULT_EASING = "inOutQuint";

// Font for the filmstrip row label (drawtext). System font, always present.
const FONT = "/System/Library/Fonts/Supplemental/Arial.ttf";
// Luma filmstrip: how many frames sampled across the dip, and each tile's width.
// FIXED count so every variant's strip shares a width (the contact sheet vstacks
// them). Dense enough that the pure-black dwell shows as several black tiles even
// for the shortest hold.
const FILMSTRIP_FRAMES = 16;
const FILMSTRIP_TILE_W = 200;

/** Parse `--key=value` argv into a plain object (first `=` splits). */
function parseArgs(argv) {
  const out = {};
  for (const arg of argv) {
    if (!arg.startsWith("--")) continue;
    const eq = arg.indexOf("=");
    if (eq === -1) out[arg.slice(2)] = true;
    else out[arg.slice(2, eq)] = arg.slice(eq + 1);
  }
  return out;
}

// public/ subdir the local source clips are staged into. The headless renderer
// serves public/ over http (it can't read file://), so a local clip must live
// under public/ and be referenced by a staticFile() path. Gitignored (shared
// with render-footage-transitions.mjs).
const STAGE_REL = "xtrans-src";

/** Make a clip loadable by OffthreadVideo. http(s) URLs pass through untouched;
 *  a local path is COPIED into public/<STAGE_REL>/ and returned as the
 *  staticFile-relative path the composition resolves via staticFile(). */
function stageClip(p, publicDir) {
  if (/^https?:\/\//.test(p)) return p;
  const abs = path.resolve(p);
  const base = path.basename(abs);
  const destDir = path.join(publicDir, STAGE_REL);
  mkdirSync(destDir, { recursive: true });
  copyFileSync(abs, path.join(destDir, base));
  return `${STAGE_REL}/${base}`;
}

/** Frames → seconds string (2dp), for labels + reporting. */
function secs(frames) {
  return (frames / FPS).toFixed(2);
}

/** Render ONE fade-to-black FootageTransition clip (select + renderMedia).
 *  Throws on failure. Duration comes from the composition's calculateMetadata
 *  (footageDurationInFrames), which reads type + the phase frame counts. */
async function doRender({ serveUrl, inputProps, outputLocation, tag }) {
  const composition = await selectComposition({
    serveUrl,
    id: "FootageTransition",
    inputProps,
    chromiumOptions: CHROMIUM_OPTIONS,
    timeoutInMilliseconds: RENDER_TIMEOUT_MS,
  });
  let lastPct = -20;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation,
    inputProps,
    chromiumOptions: CHROMIUM_OPTIONS,
    timeoutInMilliseconds: RENDER_TIMEOUT_MS,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct >= lastPct + 20) {
        lastPct = pct;
        console.log(`[xfade4] ${tag}: ${pct}%`);
      }
    },
  });
}

/** Cut a horizontal LUMA FILMSTRIP: FILMSTRIP_FRAMES frames sampled evenly across
 *  the dip (from just before the fade-out starts to just after the fade-in ends),
 *  tiled left→right with a burned row label. The pure-black dwell in the middle
 *  shows as a run of black tiles — that is the "dwell on black" made visible.
 *  FREE / local ffmpeg. */
function makeLumaFilmstrip({
  clipPath,
  outPath,
  holdFrames,
  fadeOut,
  blackHold,
  fadeIn,
  label,
}) {
  const total = 2 * holdFrames + fadeOut + blackHold + fadeIn;
  const fadeStart = holdFrames;
  const fadeInEnd = holdFrames + fadeOut + blackHold + fadeIn;
  const from = Math.max(0, fadeStart - 2);
  const to = Math.min(total - 1, fadeInEnd + 2);
  const k = FILMSTRIP_FRAMES;
  const indices = [];
  for (let i = 0; i < k; i++) {
    indices.push(Math.round(from + ((to - from) * i) / (k - 1)));
  }
  // Escape the comma inside eq(n,X) for ffmpeg's filtergraph parser.
  const sel = indices.map((f) => `eq(n\\,${f})`).join("+");
  const safeLabel = label.replace(/[':]/g, " ");
  const vf = [
    `select='${sel}'`,
    `scale=${FILMSTRIP_TILE_W}:-2`,
    `tile=${k}x1:padding=4:color=black`,
    `drawtext=fontfile=${FONT}:text='${safeLabel}':x=14:y=10:fontsize=22:` +
      `fontcolor=white:box=1:boxcolor=black@0.6`,
  ].join(",");
  const r = spawnSync(
    "ffmpeg",
    ["-y", "-hide_banner", "-loglevel", "error", "-i", clipPath, "-frames:v", "1", "-vf", vf, outPath],
    { stdio: "inherit" },
  );
  if (r.status !== 0) {
    throw new Error(`ffmpeg filmstrip exited ${r.status ?? r.signal}`);
  }
}

/** Stack the per-clip filmstrips into one contact sheet (all share a width). */
function makeContactSheet({ filmstrips, outPath }) {
  const inputs = filmstrips.flatMap((f) => ["-i", f]);
  const filter =
    filmstrips.length > 1 ? `vstack=inputs=${filmstrips.length}` : "null";
  const r = spawnSync(
    "ffmpeg",
    ["-y", "-hide_banner", "-loglevel", "error", ...inputs, "-filter_complex", filter, "-frames:v", "1", outPath],
    { stdio: "inherit" },
  );
  if (r.status !== 0) {
    throw new Error(`ffmpeg contact sheet exited ${r.status ?? r.signal}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const repoRoot = path.resolve(__dirname, "../..");
  const publicDir = path.resolve(__dirname, "../public");
  const clipA = stageClip(
    args.clipA ??
      path.join(
        repoRoot,
        "projects/7-flowers-hummingbirds-physically-cannot-resist-2/clips/scene_011.mp4",
      ),
    publicDir,
  );
  const clipB = stageClip(
    args.clipB ??
      path.join(
        repoRoot,
        "projects/7-flowers-hummingbirds-physically-cannot-resist-2/clips/scene_005.mp4",
      ),
    publicDir,
  );
  const outDir = path.resolve(args["out-dir"] ?? "/tmp/xfade4");
  const holdFrames = Math.max(1, Math.round(Number(args.holdFrames ?? 36)));
  const trimA = Math.max(0, Math.round(Number(args.trimA ?? 0)));
  const trimB = Math.max(0, Math.round(Number(args.trimB ?? 0)));
  // Curve override: when --easing is passed, OVERRIDE the veil-ramp easing on
  // EVERY variant; otherwise each variant keeps its own easing.
  const ovEasing = args.easing ?? null;
  // Per-phase overrides: when passed, OVERRIDE that phase on EVERY variant.
  const ovFadeOut =
    args.fadeOut != null ? Math.max(0, Math.round(Number(args.fadeOut))) : null;
  const ovBlackHold =
    args.blackHold != null
      ? Math.max(0, Math.round(Number(args.blackHold)))
      : null;
  const ovFadeIn =
    args.fadeIn != null ? Math.max(0, Math.round(Number(args.fadeIn))) : null;

  // The round-6 set: LONGER fades + a SHORTER black hold + a GENTLER ease than
  // round 4's inOutQuint (which crammed the motion into the middle then flattened
  // onto black — the "too-fast fade / lingers on black" tell). Each variant now
  // carries its OWN veil-ramp easing so the darkening is a smooth visible ramp.
  // Phase lengths are frames @30fps; the label reads the exact frame-derived secs.
  //   long-fade:   0.53s out + 0.13s black + 0.50s in  (inOutCubic)
  //   longer-fade: 0.70s out + 0.10s black + 0.60s in  (inOutCubic)
  //   gentle-fade: 0.60s out + 0.13s black + 0.53s in  (inOutSine)
  const VARIANTS = [
    { name: "long-fade", fadeOut: 16, blackHold: 4, fadeIn: 15, easing: "inOutCubic" },
    { name: "longer-fade", fadeOut: 21, blackHold: 3, fadeIn: 18, easing: "inOutCubic" },
    { name: "gentle-fade", fadeOut: 18, blackHold: 4, fadeIn: 16, easing: "inOutSine" },
  ];

  mkdirSync(outDir, { recursive: true });

  const entryPoint = path.resolve(__dirname, "../src/remotion/index.ts");
  console.log(`[xfade4] entry: ${entryPoint}`);
  console.log(`[xfade4] clipA: ${clipA}`);
  console.log(`[xfade4] clipB: ${clipB}`);
  console.log(`[xfade4] out-dir: ${outDir}`);
  console.log(
    `[xfade4] hold=${holdFrames}f  easing=${ovEasing ?? "(per-variant)"}  ` +
      `phase-overrides: fadeOut=${ovFadeOut ?? "(per-variant)"} ` +
      `blackHold=${ovBlackHold ?? "(per-variant)"} fadeIn=${ovFadeIn ?? "(per-variant)"}`,
  );

  console.log("[xfade4] Ensuring Remotion browser is available...");
  await ensureBrowser();

  console.log("[xfade4] Bundling composition (once)...");
  const serveUrl = await bundle({ entryPoint });

  const results = [];
  for (const v of VARIANTS) {
    const fadeOut = ovFadeOut ?? v.fadeOut;
    const blackHold = ovBlackHold ?? v.blackHold;
    const fadeIn = ovFadeIn ?? v.fadeIn;
    const easing = ovEasing ?? v.easing ?? DEFAULT_EASING;
    const totalDip = fadeOut + blackHold + fadeIn;
    const outputLocation = path.join(outDir, `${v.name}.mp4`);
    const label =
      `fade-to-black | out ${secs(fadeOut)}s / black ${secs(blackHold)}s / ` +
      `in ${secs(fadeIn)}s (${secs(totalDip)}s) | ${easing}`;
    const inputProps = {
      type: "fadeToBlack",
      params: {},
      clipA,
      clipB,
      trimA,
      trimB,
      holdFrames,
      easing,
      label,
      motionBlur: false,
      fadeOutFrames: fadeOut,
      blackHoldFrames: blackHold,
      fadeInFrames: fadeIn,
    };

    console.log(
      `\n[xfade4] === ${v.name}  out=${fadeOut}f black=${blackHold}f in=${fadeIn}f ` +
        `(dip ${totalDip}f / ${secs(totalDip)}s) easing=${easing} ===`,
    );

    let ok = false;
    try {
      await doRender({ serveUrl, inputProps, outputLocation, tag: v.name });
      ok = true;
    } catch (err) {
      console.error(
        `[xfade4] RENDER FAILED for ${v.name}: ${err && err.stack ? err.stack : String(err)}`,
      );
    }

    const result = {
      name: v.name,
      file: outputLocation,
      easing,
      fadeOut,
      blackHold,
      fadeIn,
      totalDip,
      ok,
      filmstrip: null,
    };

    if (ok) {
      console.log(`[xfade4] WROTE ${outputLocation}`);
      const filmstrip = path.join(outDir, `${v.name}.filmstrip.png`);
      try {
        makeLumaFilmstrip({
          clipPath: outputLocation,
          outPath: filmstrip,
          holdFrames,
          fadeOut,
          blackHold,
          fadeIn,
          label,
        });
        result.filmstrip = filmstrip;
        console.log(`[xfade4] WROTE ${filmstrip}`);
      } catch (err) {
        console.error(
          `[xfade4] filmstrip failed for ${v.name}: ${err && err.message ? err.message : err}`,
        );
      }
    }
    results.push(result);
  }

  // Contact sheet: stack every successful filmstrip.
  const filmstrips = results.filter((r) => r.filmstrip).map((r) => r.filmstrip);
  let contactSheet = null;
  if (filmstrips.length > 0) {
    contactSheet = path.join(outDir, "contact-sheet.png");
    try {
      makeContactSheet({ filmstrips, outPath: contactSheet });
      console.log(`[xfade4] WROTE ${contactSheet}`);
    } catch (err) {
      console.error(
        `[xfade4] contact sheet failed: ${err && err.message ? err.message : err}`,
      );
      contactSheet = null;
    }
  }

  console.log("\n[xfade4] ================ SUMMARY ================");
  for (const r of results) {
    const status = r.ok ? "OK  " : "FAIL";
    console.log(
      `[xfade4] ${status} ${r.name}  out=${secs(r.fadeOut)}s / black=${secs(r.blackHold)}s / ` +
        `in=${secs(r.fadeIn)}s (dip ${secs(r.totalDip)}s) easing=${r.easing}`,
    );
    console.log(`[xfade4]      clip:      ${r.file}`);
    if (r.filmstrip) console.log(`[xfade4]      filmstrip: ${r.filmstrip}`);
  }
  if (contactSheet) console.log(`[xfade4] contact sheet: ${contactSheet}`);
  console.log(
    "\n[xfade4] Tune the dip:\n" +
      "[xfade4]   - per-phase, ALL variants: --fadeOut=F --blackHold=F --fadeIn=F (frames @30fps)\n" +
      "[xfade4]   - veil curve, ALL variants: --easing=inOutQuint|inOutCubic|strongBezier|...\n" +
      "[xfade4]   - a bespoke SET: edit the VARIANTS array in this script\n" +
      "[xfade4]   - also: --holdFrames (per-clip on-screen hold) / --trimA / --trimB / --clipA / --clipB / --out-dir\n" +
      "[xfade4]   e.g. node scripts/render-fade-to-black.mjs --out-dir=/tmp/xfade5 --blackHold=24 --fadeIn=10",
  );
  console.log("\n[xfade4] Done.");
}

main().catch((err) => {
  const msg = err && err.stack ? err.stack : String(err);
  console.error(`[xfade4] FAILED: ${msg}`);
  process.exitCode = 1;
});
