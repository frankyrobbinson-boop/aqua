/**
 * Design-render driver for the on-screen-text (OST) overlays — v4 LOOK pass:
 * the UNIFIED FloralTag (icon + uniform-size fact + a full-width underline that
 * draws on left→right beneath the WHOLE text). MeasurementStamp is retired from
 * this test — all three facts now render as the one FloralTag treatment, so the
 * ruler fact ("Plant 2 inches deep") is just a plain fact.
 *
 * Renders OverlayFloralTag OVER one real 6-veg still at MID brightness (upper-
 * third mean luma ~117, where the chip sits) — apples-to-apples, not the blown-
 * out bright extreme. For each fact it writes a short clip (overlay animates IN →
 * holds → OUT over the still) and a 3-tile filmstrip (entrance / hold / exit),
 * then a contact sheet of every filmstrip.
 *
 * The channel TOKENS (cream/plum palette, Questrial, taupe body, duration) come
 * from the comp's defaultProps in Root.tsx (overlays/defaults.ts) — this script
 * overrides only `fact` + `backgroundSrc` + `icon` + `invert` (the per-fact
 * content + which scheme), so the LOOK tokens stay a single source of truth (see
 * overlays/scheme.ts). NOT pipeline wiring: like render-footage-transitions.mjs
 * this is a standalone look-dev renderer.
 *
 * Cream scheme only (invert=false — background=cream, ink=plum, the chosen look);
 * the file suffix `__cream` marks it. Icons are named Phosphor glyphs
 * (public/icons/phosphor/regular/<name>.svg); `calendar-dots` is the clean
 * calendar (no "12").
 *
 * Usage (all optional):
 *   node scripts/render-ost-overlays.mjs [--out-dir=/tmp/ost_v4]
 *   node scripts/render-ost-overlays.mjs --picks=/tmp/icon_eval/picks.json [--out-dir=...]
 *
 * With --picks=<json> the facts under test come from a [{icon, fact}, ...] file
 * (the icon-resolver picks written by tools/icon_resolver_eval.py) instead of the
 * built-in trio — icon:null/absent renders a text-only chip. WITHOUT --picks the
 * behavior is unchanged (the same three built-in facts over the same still).
 *
 * The renderer serves public/ over http and CANNOT read file://, so each still
 * is staged into public/ost-src/ (gitignored) and referenced via a staticFile()
 * path. Every clip is 1920x1080 / 30fps H.264.
 */
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { bundle } from "@remotion/bundler";
import {
  ensureBrowser,
  renderMedia,
  selectComposition,
} from "@remotion/renderer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Same GL backend as the other headless renderers (harmless here — no WebGL).
const CHROMIUM_OPTIONS = { gl: "angle" };
const FPS = 30;

// Shared OST grammar (mirror of overlays/animation.ts) — used only to place the
// filmstrip's entrance/exit sample frames.
const ENTER_SECONDS = 0.4;
const EXIT_SECONDS = 0.25;

// Font for the filmstrip row label (drawtext). System font, always present.
const FONT = "/System/Library/Fonts/Supplemental/Arial.ttf";
const FILMSTRIP_TILE_W = 480; // 3 tiles → 1440px-wide strip

// public/ subdir the source stills are staged into (gitignored).
const STAGE_REL = "ost-src";

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

/** Lowercase kebab slug of a fact, for the per-clip filename key. */
function slug(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Build the FACTS list from a --picks JSON file: [{icon, fact}, ...] as written
 *  by tools/icon_resolver_eval.py. Each becomes a FloralTag entry; `icon` null or
 *  absent => a text-only chip. Shape mirrors the built-in FACTS below. */
function factsFromPicks(picksPath) {
  const abs = path.resolve(picksPath);
  const picks = JSON.parse(readFileSync(abs, "utf8"));
  if (!Array.isArray(picks)) {
    throw new Error(`--picks must be a JSON array of {icon, fact}: ${abs}`);
  }
  return picks.map((p, i) => {
    const fact = String(p?.fact ?? "");
    return {
      compId: "OverlayFloralTag",
      short: "tag",
      key: slug(fact) || `pick-${i}`,
      icon: p?.icon ?? null, // null/absent => text-only chip (FloralTag guards it)
      fact,
    };
  });
}

/** Copy a still into public/<STAGE_REL>/ and return the staticFile-relative path
 *  the comp resolves via staticFile(). */
function stageStill(abs, publicDir) {
  const base = path.basename(abs);
  const destDir = path.join(publicDir, STAGE_REL);
  mkdirSync(destDir, { recursive: true });
  copyFileSync(abs, path.join(destDir, base));
  return `${STAGE_REL}/${base}`;
}

/** Render ONE overlay clip (select + renderMedia). Returns the composition's
 *  resolved durationInFrames (from calculateMetadata) for the filmstrip. */
async function doRender({ serveUrl, compId, inputProps, outputLocation, tag }) {
  const composition = await selectComposition({
    serveUrl,
    id: compId,
    inputProps,
    chromiumOptions: CHROMIUM_OPTIONS,
  });
  let lastPct = -20;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation,
    inputProps,
    chromiumOptions: CHROMIUM_OPTIONS,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct >= lastPct + 20) {
        lastPct = pct;
        console.log(`[ost] ${tag}: ${pct}%`);
      }
    },
  });
  return composition.durationInFrames;
}

/** Cut a 3-tile ENTRANCE / HOLD / EXIT filmstrip with a burned row label. */
function makeFilmstrip({ clipPath, outPath, totalFrames, label }) {
  const enter = Math.max(1, Math.round(ENTER_SECONDS * FPS));
  const exit = Math.max(1, Math.round(EXIT_SECONDS * FPS));
  const frames = [
    Math.round(enter * 0.6), // mid-entrance (sliding up + fading in)
    Math.round(totalFrames / 2), // hold (dead still)
    Math.max(0, totalFrames - Math.round(exit * 0.5)), // mid-exit (fading out)
  ];
  // Escape the comma inside eq(n,X) for ffmpeg's filtergraph parser.
  const sel = frames.map((f) => `eq(n\\,${f})`).join("+");
  const safeLabel = label.replace(/[':]/g, " ");
  const vf = [
    `select='${sel}'`,
    `scale=${FILMSTRIP_TILE_W}:-2`,
    `tile=3x1:padding=6:color=white`,
    `drawtext=fontfile=${FONT}:text='${safeLabel}':x=16:y=12:fontsize=24:` +
      `fontcolor=white:box=1:boxcolor=black@0.6`,
  ].join(",");
  const r = spawnSync(
    "ffmpeg",
    ["-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", clipPath, "-frames:v", "1", "-vf", vf, outPath],
    { stdio: "inherit" },
  );
  if (r.status !== 0) throw new Error(`ffmpeg filmstrip exited ${r.status ?? r.signal}`);
}

/** Stack every per-clip filmstrip into one contact sheet (all share a width). */
function makeContactSheet({ filmstrips, outPath }) {
  const inputs = filmstrips.flatMap((f) => ["-i", f]);
  const filter = filmstrips.length > 1 ? `vstack=inputs=${filmstrips.length}` : "null";
  const r = spawnSync(
    "ffmpeg",
    ["-y", "-nostdin", "-hide_banner", "-loglevel", "error", ...inputs, "-filter_complex", filter, "-frames:v", "1", outPath],
    { stdio: "inherit" },
  );
  if (r.status !== 0) throw new Error(`ffmpeg contact sheet exited ${r.status ?? r.signal}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, "../..");
  const publicDir = path.resolve(__dirname, "../public");
  const outDir = path.resolve(args["out-dir"] ?? "/tmp/ost_v4");
  mkdirSync(outDir, { recursive: true });

  // ONE mid-brightness 6-veg still (upper-third mean luma ~117, where the chip
  // sits) so the three treatments compare apples-to-apples — NOT the blown-out
  // bright extreme. Swap `file` to re-judge over a different background.
  const FOOTAGE_DIR = path.join(
    repoRoot,
    "projects/6-vegetables-you-plant-once-and-harvest-for-20-years/footage",
  );
  const BACKGROUNDS = [
    { key: "mid", file: "scene_073.png", luma: 117 }, // vegetable in a planter
  ].map((b) => ({
    ...b,
    src: stageStill(path.join(FOOTAGE_DIR, b.file), publicDir),
  }));

  // The three facts under test — all now the UNIFIED FloralTag (uniform text +
  // full-width underline); the ruler fact ("Plant 2 inches deep") is just a plain
  // fact now, no longer a number-hero stamp. calendar-dots is the clean calendar
  // (no "12").
  const DEFAULT_FACTS = [
    {
      compId: "OverlayFloralTag",
      short: "tag",
      key: "ruler",
      icon: "ruler",
      fact: "Plant 2 inches deep",
    },
    {
      compId: "OverlayFloralTag",
      short: "tag",
      key: "sun",
      icon: "sun",
      fact: "6 hours of sun",
    },
    {
      compId: "OverlayFloralTag",
      short: "tag",
      key: "divide",
      icon: "calendar-dots",
      fact: "Divide every 2-3 years",
    },
  ];

  // With --picks=<json>, draw the icon-resolver picks ([{icon, fact}, ...], written
  // by tools/icon_resolver_eval.py) instead of the built-in trio — icon:null => a
  // text-only chip. Without --picks, FACTS is the built-in DEFAULT_FACTS above and
  // the render is byte-for-byte the same as before.
  const FACTS = args.picks ? factsFromPicks(args.picks) : DEFAULT_FACTS;

  // Cream scheme only (invert=false — background=cream, ink=plum, the chosen
  // look). One-element list so the loop / filename suffix stay unchanged; add
  // { key: "plum", invert: true } to re-compare the inverted chip.
  const SCHEMES = [{ key: "cream", invert: false }];

  const entryPoint = path.resolve(__dirname, "../src/remotion/index.ts");
  console.log(`[ost] entry: ${entryPoint}`);
  console.log(`[ost] out-dir: ${outDir}`);
  for (const b of BACKGROUNDS) console.log(`[ost] bg ${b.key}: ${b.src} (luma≈${b.luma})`);

  console.log("[ost] Ensuring Remotion browser is available...");
  await ensureBrowser();
  console.log("[ost] Bundling composition (once)...");
  const serveUrl = await bundle({ entryPoint });

  const results = [];
  for (const f of FACTS) {
    for (const s of SCHEMES) {
      for (const bg of BACKGROUNDS) {
        // Name: tag__<fact>__<bg>__<scheme> (one scheme/bg now → 3 clips total).
        const name = `${f.short}__${f.key}__${bg.key}__${s.key}`;
        const outputLocation = path.join(outDir, `${name}.mp4`);
        const iconLabel = f.icon ?? "text-only"; // logs/labels only; null = no icon
        // Override the per-fact content (fact / icon) + the scheme (invert) + the
        // design-render background; the LOOK tokens come from the comp defaults.
        // icon:null overrides the comp default to render a text-only chip.
        const inputProps = {
          fact: f.fact,
          backgroundSrc: bg.src,
          icon: f.icon,
          invert: s.invert,
        };
        console.log(`\n[ost] === ${name} (${f.compId}) ${iconLabel} + "${f.fact}" | ${s.key} chip over ${bg.file} ===`);
        let ok = false;
        let filmstrip = null;
        try {
          const totalFrames = await doRender({
            serveUrl,
            compId: f.compId,
            inputProps,
            outputLocation,
            tag: name,
          });
          ok = true;
          console.log(`[ost] WROTE ${outputLocation}`);
          filmstrip = path.join(outDir, `${name}.filmstrip.png`);
          const label = `${f.short} | ${iconLabel} | "${f.fact}" | ${s.key} chip | ${bg.key} (luma ${bg.luma}) | in-hold-out`;
          try {
            makeFilmstrip({ clipPath: outputLocation, outPath: filmstrip, totalFrames, label });
            console.log(`[ost] WROTE ${filmstrip}`);
          } catch (err) {
            console.error(`[ost] filmstrip failed for ${name}: ${err && err.message ? err.message : err}`);
            filmstrip = null;
          }
        } catch (err) {
          console.error(`[ost] RENDER FAILED for ${name}: ${err && err.stack ? err.stack : String(err)}`);
        }
        results.push({ name, comp: f.compId, fact: f.fact, scheme: s.key, bg: bg.key, file: outputLocation, ok, filmstrip });
      }
    }
  }

  // Contact sheet: every successful filmstrip, stacked.
  const filmstrips = results.filter((r) => r.filmstrip).map((r) => r.filmstrip);
  let contactSheet = null;
  if (filmstrips.length > 0) {
    contactSheet = path.join(outDir, "contact-sheet.png");
    try {
      makeContactSheet({ filmstrips, outPath: contactSheet });
      console.log(`[ost] WROTE ${contactSheet}`);
    } catch (err) {
      console.error(`[ost] contact sheet failed: ${err && err.message ? err.message : err}`);
      contactSheet = null;
    }
  }

  console.log("\n[ost] ================ SUMMARY ================");
  for (const r of results) {
    console.log(`[ost] ${r.ok ? "OK  " : "FAIL"} ${r.name}`);
    console.log(`[ost]      clip:      ${r.file}`);
    if (r.filmstrip) console.log(`[ost]      filmstrip: ${r.filmstrip}`);
  }
  if (contactSheet) console.log(`[ost] contact sheet: ${contactSheet}`);
  console.log("\n[ost] Done.");
}

main().catch((err) => {
  console.error(`[ost] FAILED: ${err && err.stack ? err.stack : String(err)}`);
  process.exitCode = 1;
});
