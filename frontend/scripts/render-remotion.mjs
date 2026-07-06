/**
 * Programmatic Remotion renderer for the Aqua "/remotion" tab.
 *
 * Usage:
 *   node scripts/render-remotion.mjs --comp=TitleCard \
 *     --props='{"title":"Hello Aqua"}' --out=/abs/path/out.mp4
 *
 * Invoked by the FastAPI task runner (backend/api/routes/remotion.py) with
 * cwd=<frontend>. It bundles src/remotion/index.ts, selects the composition,
 * and renders an H.264 MP4 to --out. Progress + `[[STAGE:render:...]]` markers
 * stream on stdout so the SSE task log shows live progress. We use the
 * programmatic API (not the `remotion` CLI) so we control the args and stream.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { bundle } from "@remotion/bundler";
import {
  ensureBrowser,
  renderMedia,
  selectComposition,
} from "@remotion/renderer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
  });

  console.log("[render] Rendering media (h264)...");
  let lastRenderPct = -5;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation,
    inputProps,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct >= lastRenderPct + 5) {
        lastRenderPct = pct;
        console.log(`[render] Rendering: ${pct}%`);
      }
    },
  });

  console.log(`[render] Wrote ${outputLocation}`);
  console.log("[[STAGE:render:completed]]");
}

main().catch((err) => {
  console.error(`[render] FAILED: ${err && err.stack ? err.stack : err}`);
  process.exitCode = 1;
});
