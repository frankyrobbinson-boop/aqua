/**
 * Programmatic Remotion renderer for the Aqua "/remotion" tab.
 *
 * Usage:
 *   node scripts/render-remotion.mjs --comp=TitleCard \
 *     --props='{"title":"Hello Aqua"}' --out=/abs/path/out.mp4
 *
 * Invoked by the FastAPI task runner (backend/api/routes/remotion.py) with
 * cwd=<frontend>. It bundles src/remotion/index.ts, selects the composition,
 * and renders to --out. Default is an H.264 MP4; `--codec=prores --alpha`
 * (`--prores-profile=4444`) renders a TRANSPARENT ProRes 4444 .mov instead — the
 * over-footage fact chips assembly_service composites. Progress +
 * `[[STAGE:render:...]]` markers stream on stdout so the SSE task log shows live
 * progress. We use the programmatic API (not the `remotion` CLI) so we control
 * the args and stream.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { bundle } from "@remotion/bundler";
import {
  ensureBrowser,
  renderMedia,
  selectComposition,
} from "@remotion/renderer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// GL backend for the headless Chromium. Tier-B transitions (the
// @remotion/transitions WebGL shaders, rendered html-in-canvas) need a real GL
// context to render off-screen; "angle" works on this machine and is harmless
// for the card renders (they use no WebGL). If a render fails inside GL, the
// software fallback is "swangle" (see the failure hint in main's catch).
const CHROMIUM_OPTIONS = { gl: "angle" };

/** Parse `--key=value` argv into a plain object. Splits on the FIRST `=` so
 *  JSON values (which contain no `=`) pass through intact. */
function parseArgs(argv) {
  const out = {};
  for (const arg of argv) {
    if (!arg.startsWith("--")) continue;
    const eq = arg.indexOf("=");
    if (eq === -1) {
      out[arg.slice(2)] = true;
    } else {
      out[arg.slice(2, eq)] = arg.slice(eq + 1);
    }
  }
  return out;
}

/**
 * Load the raw Lottie JSON for each GardenBloom `lottieAnimations` row into the
 * runtime `lottieData` shape the card consumes — the SAME array CardDesigner
 * builds client-side for the <Player>, so the MP4 bakes in the same decorations
 * the preview shows. The endpoint forwards only the small config (names +
 * loop/recolor); the big JSON is read HERE, server-side, from public/lottie.
 *
 * One entry per row, IN ORDER, so the card's `entries[i % entries.length]`
 * cycling matches the preview's alignment. `name` may or may not carry the
 * `.json` extension; a missing or unparseable file becomes `data: null` (the
 * card filters those out via isLikelyLottie) plus a logged warning. `basename`
 * confines the read to the lottie dir. Deterministic — no Date.now / random.
 */
function loadLottieData(animations, dirname) {
  const dir = path.resolve(dirname, "../public/lottie");
  return animations.map((row) => {
    const base = path.basename(String((row && row.name) || ""));
    const file = base.toLowerCase().endsWith(".json") ? base : `${base}.json`;
    let data = null;
    try {
      data = JSON.parse(readFileSync(path.join(dir, file), "utf8"));
    } catch (err) {
      console.warn(
        `[render] Lottie load failed for ${file}: ${
          err && err.message ? err.message : err
        }`,
      );
    }
    return {
      data,
      loop: (row && row.loop) ?? true,
      recolor: (row && row.recolor) ?? true,
    };
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const compId = args.comp;
  const outArg = args.out;
  if (!compId || !outArg) {
    throw new Error(
      "Missing required args. Expected --comp=<id> --out=<path> [--props=<json>]",
    );
  }

  const inputProps = args.props ? JSON.parse(args.props) : {};

  // Codec selection. Default h264 (the /remotion card path — byte-identical to
  // before). `--codec=prores` with `--alpha` renders a TRANSPARENT ProRes 4444
  // (yuva444p10le + PNG frame extraction, supported by @remotion/renderer here) —
  // the over-footage fact chips the pipeline composites.
  const codec = typeof args.codec === "string" ? args.codec : "h264";
  const proResProfile =
    typeof args["prores-profile"] === "string" ? args["prores-profile"] : "4444";
  const wantAlpha =
    args.alpha === true || args.alpha === "true" || args.alpha === "1";

  // Bake GardenBloom's Lottie decorations into the MP4: the endpoint forwards
  // only the small lottie CONFIG (names + loop/recolor, density, amount), so we
  // load each animation's JSON here and attach it as `lottieData` — the exact
  // shape GardenBloom's LottieDecor consumes (and the <Player> preview builds
  // client-side). This augmented `inputProps` feeds BOTH selectComposition and
  // renderMedia below, so metadata + frames see the same decorations.
  if (
    Array.isArray(inputProps.lottieAnimations) &&
    inputProps.lottieAnimations.length > 0
  ) {
    inputProps.lottieData = loadLottieData(inputProps.lottieAnimations, __dirname);
  }

  const outputLocation = path.resolve(process.cwd(), outArg);
  const entryPoint = path.resolve(__dirname, "../src/remotion/index.ts");

  console.log(`[render] entry: ${entryPoint}`);
  console.log(`[render] composition: ${compId}`);
  console.log(`[render] output: ${outputLocation}`);
  console.log("[[STAGE:render:started]]");

  // Make sure the headless browser exists. The FIRST render downloads it
  // (~150-300MB, one-time) — announce it clearly so the task log doesn't look
  // hung. onBrowserDownload only fires when an actual download happens, so
  // subsequent renders stay quiet.
  console.log("[render] Ensuring Remotion browser is available...");
  await ensureBrowser({
    onBrowserDownload: () => {
      console.log(
        "First render: downloading Remotion browser (one-time, ~200MB)... this can take a minute.",
      );
      let lastLogged = -10;
      return {
        version: null,
        onProgress: ({ percent }) => {
          const pct = Math.floor(percent * 100);
          // Log every ~10% so the stream shows life without flooding it.
          if (pct >= lastLogged + 10) {
            lastLogged = pct;
            console.log(`[render] Browser download: ${pct}%`);
          }
        },
      };
    },
  });

  console.log("[render] Bundling composition...");
  let lastBundlePct = -25;
  const serveUrl = await bundle({
    entryPoint,
    onProgress: (progress) => {
      const pct = Math.floor(progress);
      if (pct >= lastBundlePct + 25) {
        lastBundlePct = pct;
        console.log(`[render] Bundling: ${pct}%`);
      }
    },
  });

  console.log("[render] Selecting composition...");
  const composition = await selectComposition({
    serveUrl,
    id: compId,
    inputProps,
    chromiumOptions: CHROMIUM_OPTIONS,
  });

  if (codec === "prores") {
    console.log(
      `[render] Rendering media (prores ${proResProfile}${
        wantAlpha ? " alpha" : ""
      }, gl=${CHROMIUM_OPTIONS.gl})...`,
    );
    let lastRenderPct = -5;
    await renderMedia({
      composition,
      serveUrl,
      codec: "prores",
      proResProfile,
      // Transparent renders need the alpha-carrying pixel format + PNG frame
      // extraction; opaque ProRes leaves these to the codec default.
      ...(wantAlpha ? { pixelFormat: "yuva444p10le", imageFormat: "png" } : {}),
      outputLocation,
      inputProps,
      chromiumOptions: CHROMIUM_OPTIONS,
      onProgress: ({ progress }) => {
        const pct = Math.floor(progress * 100);
        if (pct >= lastRenderPct + 5) {
          lastRenderPct = pct;
          console.log(`[render] Rendering: ${pct}%`);
        }
      },
    });
  } else {
    console.log(`[render] Rendering media (h264, gl=${CHROMIUM_OPTIONS.gl})...`);
    let lastRenderPct = -5;
    await renderMedia({
      composition,
      serveUrl,
      codec: "h264",
      outputLocation,
      inputProps,
      chromiumOptions: CHROMIUM_OPTIONS,
      onProgress: ({ progress }) => {
        const pct = Math.floor(progress * 100);
        if (pct >= lastRenderPct + 5) {
          lastRenderPct = pct;
          console.log(`[render] Rendering: ${pct}%`);
        }
      },
    });
  }

  console.log(`[render] Wrote ${outputLocation}`);
  console.log("[[STAGE:render:completed]]");
}

main().catch((err) => {
  const msg = err && err.stack ? err.stack : String(err);
  console.error(`[render] FAILED: ${msg}`);
  // Tier-B shader transitions render through a WebGL context (chromiumOptions.gl,
  // set to "angle" above). Surface a clear hint when a failure looks GL-related
  // so the fix — swapping to the "swangle" software backend — is obvious.
  if (/webgl|angle|gl_|context lost|gpu|swiftshader/i.test(msg)) {
    console.error(
      `[render] Hint: this looks GL-related. Shader transitions render with ` +
        `chromiumOptions.gl="${CHROMIUM_OPTIONS.gl}"; "swangle" is a software fallback.`,
    );
  }
  process.exitCode = 1;
});
