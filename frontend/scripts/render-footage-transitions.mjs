/**
 * Batch renderer for footage-to-footage transition RATING clips — ROUND 3
 * (aggressive ease-in-out + MOTION BLUR).
 *
 * Bundles src/remotion/index.ts ONCE, then renders the `FootageTransition`
 * composition for a CURATED round-3 set over two REAL clips, each with its own
 * easing / duration / motion-blur, plus a burned-in corner label
 * (type / easing / duration / "+motionblur"). After each clip it cuts a SEAM
 * FILMSTRIP (frames sampled across the transition) and finally stacks them into
 * one contact sheet (ffmpeg). Every clip is 1920x1080/30fps H.264.
 *
 * Round-3 direction (from the user's reference clips): keep the ease-in-out
 * SHAPE but make the curve MUCH MORE AGGRESSIVE without rushing the motion (so a
 * comfortable ~0.7s duration), and add real MOTION BLUR to the moving
 * transitions (the biggest missing ingredient vs the 60fps refs; our finals are
 * 25fps). Motion blur is `@remotion/motion-blur`'s CameraMotionBlur, wrapped in
 * FootageTransition when `motionBlur` is set.
 *
 * Usage (all optional; sensible 7-flowers defaults):
 *   node scripts/render-footage-transitions.mjs \
 *     [--clipA=/abs/a.mp4] [--clipB=/abs/b.mp4] [--out-dir=/tmp/xtrans2] \
 *     [--easing=strongBezier] [--transitionFrames=21] [--holdFrames=36] \
 *     [--shutterAngle=200] [--samples=12] [--trimA=0] [--trimB=0]
 *
 * `--easing` / `--transitionFrames`, when passed, OVERRIDE every clip (sweep the
 * whole set); otherwise each clip keeps its own round-3 easing/duration.
 * `--shutterAngle` / `--samples` tune the motion blur on the moving clips.
 *
 * To render ONE arbitrary transition/easing/duration instead, stage a clip under
 * frontend/public/ (the renderer serves public/ over http, it can't read
 * file://) and use the existing single-comp path with a staticFile() path:
 *   node scripts/render-remotion.mjs --comp=FootageTransition \
 *     --props='{"type":"slide","params":{"direction":"from-right","durationInFrames":21},
 *              "clipA":"xtrans-src/a.mp4","clipB":"xtrans-src/b.mp4",
 *              "trimA":0,"trimB":0,"holdFrames":36,"easing":"strongBezier",
 *              "motionBlur":true,"label":"slide | strongBezier | 0.70s | +motionblur"}' \
 *     --out=/tmp/xtrans2/slide.mp4
 *
 * Reuses the same gl:angle Chromium backend as render-remotion.mjs so the Tier-B
 * shader transitions (zoomBlur) render headless off-screen. If a
 * motion-blur + shader combo fails headless, the clip is retried once WITHOUT
 * motion blur and flagged (see the per-clip fallback below).
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

// Same GL backend as render-remotion.mjs — the Tier-B shader transitions need a
// real off-screen GL context; "swangle" is the software fallback if it fails.
const CHROMIUM_OPTIONS = { gl: "angle" };

// Composition fps (mirror of src/remotion/constants.ts FPS) — used to convert
// transition frame counts to the seconds shown on the label + to place the seam.
const FPS = 30;

// Per-frame render/delayRender budget. CameraMotionBlur forces ~`samples`
// fractional-time OffthreadVideo fetches per frame (and, on a shader transition,
// that many shader passes), which blows past Remotion's default 30s frame
// timeout under proxy contention. Give each frame a generous budget so the
// moving clips render headless instead of tripping a spurious timeout.
const RENDER_TIMEOUT_MS = 240000;

// Render concurrency for the MOTION-BLUR clips. Default concurrency renders many
// frames in parallel, each firing ~`samples` fractional-time OffthreadVideo
// proxy fetches; that overloads the local frame server and it starts hard-
// failing fetches ("Failed to fetch ... /proxy?src=..."). Serialising the
// motion-blur renders keeps the proxy stable (slower, but reliable). The
// non-motion-blur clips render at Remotion's default concurrency.
const MOTION_BLUR_CONCURRENCY = 1;

// Font for the filmstrip row label (drawtext). System font, always present.
const FONT = "/System/Library/Fonts/Supplemental/Arial.ttf";
// Seam filmstrip: how many frames across the transition, and each tile's width.
const FILMSTRIP_FRAMES = 8;
const FILMSTRIP_TILE_W = 360;

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
// under public/ and be referenced by a staticFile() path. Gitignored.
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

/** Render ONE FootageTransition clip (select + renderMedia). Throws on failure.
 *  `concurrency` (optional) caps parallel frame renders — set low for
 *  motion-blur clips so the OffthreadVideo proxy stays stable. */
async function doRender({ serveUrl, inputProps, outputLocation, tag, concurrency }) {
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
    ...(concurrency != null ? { concurrency } : {}),
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct >= lastPct + 20) {
        lastPct = pct;
        console.log(`[xtrans2] ${tag}: ${pct}%`);
      }
    },
  });
}

/** Cut a horizontal SEAM FILMSTRIP: FILMSTRIP_FRAMES frames sampled evenly from
 *  just before the transition to just after it (the seam sits at hold +
 *  transition/2), tiled left→right with a burned row label. FREE / local ffmpeg. */
function makeFilmstrip({ clipPath, outPath, holdFrames, transitionFrames, label }) {
  const total = transitionFrames + 2 * holdFrames;
  const from = Math.max(0, holdFrames - 2);
  const to = Math.min(total - 1, holdFrames + transitionFrames + 2);
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
  const outDir = path.resolve(args["out-dir"] ?? "/tmp/xtrans2");
  const holdFrames = Math.max(1, Math.round(Number(args.holdFrames ?? 36)));
  const trimA = Math.max(0, Math.round(Number(args.trimA ?? 0)));
  const trimB = Math.max(0, Math.round(Number(args.trimB ?? 0)));
  // When passed, these OVERRIDE every clip's own easing/duration (whole-set sweep).
  const globalEasing = args.easing ?? null;
  const globalFrames =
    args.transitionFrames != null
      ? Math.max(1, Math.round(Number(args.transitionFrames)))
      : null;
  // Motion-blur tuning (applied to the moving clips only).
  const globalShutter = args.shutterAngle != null ? Number(args.shutterAngle) : null;
  const globalSamples =
    args.samples != null ? Math.round(Number(args.samples)) : null;
  // Concurrency for the motion-blur clips (low = stable proxy; see const).
  const motionBlurConcurrency =
    args.concurrency != null
      ? Math.max(1, Math.round(Number(args.concurrency)))
      : MOTION_BLUR_CONCURRENCY;

  // The round-3 set. Each clip carries its own `easing`, `transitionFrames`
  // (@30fps: 21 = 0.70s, 27 = 0.90s) and `motionBlur`. `display` is the human
  // name in the label; `params` carries the presentation's knob(s).
  const VARIANTS = [
    { name: "01-fade-to-black", type: "fadeToBlack", display: "fade-to-black", params: {}, easing: "inOutQuint", transitionFrames: 21, motionBlur: false },
    { name: "02-swipe-slide-mblur", type: "slide", display: "swipe/slide", params: { direction: "from-right" }, easing: "strongBezier", transitionFrames: 21, motionBlur: true },
    { name: "03-blur-dissolve", type: "blurDissolve", display: "blur-dissolve", params: {}, easing: "strongBezier", transitionFrames: 21, motionBlur: false },
    // zoom-blur is a Tier-B WebGL shader; CameraMotionBlur renders it `samples`
    // times PER FRAME, so use fewer samples here to keep the shader+motion-blur
    // combo feasible headless (see RENDER_TIMEOUT_MS). Falls back to shader-only
    // if it still can't render.
    { name: "04-zoom-blur-mblur", type: "zoomBlur", display: "zoom-blur", params: { rotation: 0.4 }, easing: "strongBezier", transitionFrames: 21, motionBlur: true, samples: 6 },
    { name: "05-swipe-slide-090-mblur", type: "slide", display: "swipe/slide", params: { direction: "from-right" }, easing: "strongBezier", transitionFrames: 27, motionBlur: true },
  ];

  mkdirSync(outDir, { recursive: true });

  const entryPoint = path.resolve(__dirname, "../src/remotion/index.ts");
  console.log(`[xtrans2] entry: ${entryPoint}`);
  console.log(`[xtrans2] clipA: ${clipA}`);
  console.log(`[xtrans2] clipB: ${clipB}`);
  console.log(`[xtrans2] out-dir: ${outDir}`);
  console.log(
    `[xtrans2] hold=${holdFrames}f  easing-override=${globalEasing ?? "(per-clip)"}  ` +
      `frames-override=${globalFrames ?? "(per-clip)"}  shutter=${globalShutter ?? "default"}  ` +
      `samples=${globalSamples ?? "default"}  mblur-concurrency=${motionBlurConcurrency}`,
  );

  console.log("[xtrans2] Ensuring Remotion browser is available...");
  await ensureBrowser();

  console.log("[xtrans2] Bundling composition (once)...");
  const serveUrl = await bundle({ entryPoint });

  const results = [];
  for (const v of VARIANTS) {
    const easing = globalEasing ?? v.easing;
    const transitionFrames = globalFrames ?? v.transitionFrames;
    const durSec = (transitionFrames / FPS).toFixed(2);
    const outputLocation = path.join(outDir, `${v.name}.mp4`);
    const mbTag = v.motionBlur ? " | +motionblur" : "";
    const label = `${v.display} | ${easing} | ${durSec}s${mbTag}`;
    const inputProps = {
      type: v.type,
      params: { ...v.params, durationInFrames: transitionFrames },
      clipA,
      clipB,
      trimA,
      trimB,
      holdFrames,
      easing,
      label,
      motionBlur: v.motionBlur,
      ...(v.motionBlur && globalShutter != null ? { shutterAngle: globalShutter } : {}),
      // Samples: CLI override wins, else the clip's own override (e.g. the
      // shader zoom), else the component default.
      ...(v.motionBlur && (globalSamples ?? v.samples) != null
        ? { samples: globalSamples ?? v.samples }
        : {}),
    };

    console.log(
      `\n[xtrans2] === ${v.name} (${v.type}) easing=${easing} dur=${transitionFrames}f motionBlur=${v.motionBlur} ===`,
    );

    let ok = false;
    let motionBlurApplied = v.motionBlur;
    let note = "";
    try {
      await doRender({
        serveUrl,
        inputProps,
        outputLocation,
        tag: v.name,
        // Serialise the motion-blur renders so the OffthreadVideo proxy is stable.
        concurrency: v.motionBlur ? motionBlurConcurrency : undefined,
      });
      ok = true;
    } catch (err) {
      const msg = err && err.stack ? err.stack : String(err);
      console.error(`[xtrans2] RENDER FAILED for ${v.name}: ${msg}`);
      if (v.motionBlur) {
        // The flagged risk: a motion-blur + WebGL-shader combo may not render
        // headless. Fall back to the SAME clip without motion blur so the round
        // still has a comparison, and flag it clearly.
        console.warn(
          `[xtrans2] ${v.name}: retrying WITHOUT motion blur (motion-blur+shader combo may not render headless)...`,
        );
        const fbLabel = `${v.display} | ${easing} | ${durSec}s (motionblur FAILED->off)`;
        try {
          await doRender({
            serveUrl,
            inputProps: { ...inputProps, motionBlur: false, label: fbLabel },
            outputLocation,
            tag: `${v.name} (fallback)`,
          });
          ok = true;
          motionBlurApplied = false;
          note = "motion-blur render failed headless; fell back to NO motion blur";
        } catch (err2) {
          console.error(
            `[xtrans2] FALLBACK ALSO FAILED for ${v.name}: ${err2 && err2.stack ? err2.stack : String(err2)}`,
          );
        }
      }
    }

    const result = {
      name: v.name,
      type: v.type,
      file: outputLocation,
      easing,
      durSec,
      transitionFrames,
      requestedMotionBlur: v.motionBlur,
      motionBlurApplied,
      ok,
      note,
      filmstrip: null,
    };

    if (ok) {
      console.log(`[xtrans2] WROTE ${outputLocation}`);
      const filmstrip = path.join(outDir, `${v.name}.filmstrip.png`);
      const fsMb = motionBlurApplied
        ? " | +motionblur"
        : v.motionBlur
          ? " | motionblur OFF (fallback)"
          : "";
      const fsLabel = `${v.display} | ${easing} | ${durSec}s${fsMb}`;
      try {
        makeFilmstrip({ clipPath: outputLocation, outPath: filmstrip, holdFrames, transitionFrames, label: fsLabel });
        result.filmstrip = filmstrip;
        console.log(`[xtrans2] WROTE ${filmstrip}`);
      } catch (err) {
        console.error(
          `[xtrans2] filmstrip failed for ${v.name}: ${err && err.message ? err.message : err}`,
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
      console.log(`[xtrans2] WROTE ${contactSheet}`);
    } catch (err) {
      console.error(
        `[xtrans2] contact sheet failed: ${err && err.message ? err.message : err}`,
      );
      contactSheet = null;
    }
  }

  console.log("\n[xtrans2] ================ SUMMARY ================");
  for (const r of results) {
    const status = r.ok ? "OK  " : "FAIL";
    const mb = r.motionBlurApplied
      ? "motionblur=ON"
      : r.requestedMotionBlur
        ? "motionblur=FELL-BACK-OFF"
        : "motionblur=off";
    console.log(
      `[xtrans2] ${status} ${r.name}  type=${r.type} easing=${r.easing} dur=${r.durSec}s ${mb}`,
    );
    console.log(`[xtrans2]      clip:      ${r.file}`);
    if (r.filmstrip) console.log(`[xtrans2]      filmstrip: ${r.filmstrip}`);
    if (r.note) console.log(`[xtrans2]      note:      ${r.note}`);
  }
  if (contactSheet) console.log(`[xtrans2] contact sheet: ${contactSheet}`);
  console.log(
    "\n[xtrans2] Re-run the WHOLE set with a new easing/duration, e.g.:\n" +
      "[xtrans2]   node scripts/render-footage-transitions.mjs --out-dir=/tmp/xtrans3 --easing=inOutQuint --transitionFrames=24\n" +
      "[xtrans2] (--easing overrides every clip; --transitionFrames is frames @30fps; --shutterAngle/--samples\n" +
      "[xtrans2]  tune motion blur; --concurrency raises the motion-blur render concurrency (default 1 = most\n" +
      "[xtrans2]  stable); --holdFrames/--trimA/--trimB/--clipA/--clipB also available.)",
  );
  console.log("\n[xtrans2] Done.");
}

main().catch((err) => {
  const msg = err && err.stack ? err.stack : String(err);
  console.error(`[xtrans2] FAILED: ${msg}`);
  if (/webgl|angle|gl_|context lost|gpu|swiftshader/i.test(msg)) {
    console.error(
      `[xtrans2] Hint: GL-related. Shader transitions render with ` +
        `chromiumOptions.gl="${CHROMIUM_OPTIONS.gl}"; "swangle" is a software fallback.`,
    );
  }
  process.exitCode = 1;
});
