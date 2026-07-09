/**
 * One-off build tool: extract reusable assets from the "Floral Slides" SVG set
 * for the Floral Card style (see src/remotion/cards/floral/).
 *
 * For each slide it:
 *   1. (slide 1 only) decodes the embedded paper-texture JPEG and downscales it
 *      to public/cardstyle/texture.jpg — the shared card background. The texture
 *      is identical across every slide, so we grab it once.
 *   2. rasterizes the whole slide at high res, cream-keys the paper background to
 *      transparent, ZEROES a per-slide text-safe region so the outlined title/body
 *      glyphs are never captured, then segments the remaining art into INDIVIDUAL
 *      FLOWERS via connected-component labeling — each component (a whole flower,
 *      or a cluster of touching flowers) is exported as its own tight, alpha PNG
 *      to public/cardstyle/botanicals/slideNN-KK.png. A small morphological
 *      DILATION bridges gaps left by cream-keyed pale petals BEFORE labeling so a
 *      flower stays one component, but only the ORIGINAL keyed pixels of that
 *      component are exported (the art is never fattened, and neighbouring
 *      components are masked out so crops don't bleed into each other).
 *   3. records every PNG (source slide + normalized content bbox over the
 *      1440x810 slide) in public/cardstyle/manifest.json — the record the floral
 *      variants table is transcribed from.
 *
 * Run from the frontend dir:  node scripts/extract-floral-assets.mjs
 * Deterministic (no timestamps / randomness) so re-running is reproducible.
 * Uses the hoisted `sharp` in frontend/node_modules.
 *
 * NOTE: only the two pilot slides (1 + 2) are wired up so far; add more to SLIDES
 * as they are designed.
 */
import { mkdirSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Repo layout: this script lives in frontend/scripts.
const FRONTEND_DIR = path.resolve(__dirname, "..");
const REPO_DIR = path.resolve(FRONTEND_DIR, "..");
const SLIDES_DIR = path.join(REPO_DIR, "assets", "Remotion", "Floral Slides");
const OUT_DIR = path.join(FRONTEND_DIR, "public", "cardstyle");
const BOTANICALS_DIR = path.join(OUT_DIR, "botanicals");

// High-res raster width for the whole-slide render we segment. The slides are
// 16:9, so height derives to 2160. density high enough that the vector art is
// crisp before downscale.
const RASTER_WIDTH = 3840;
const RASTER_DENSITY = 200;

// Shared background texture size (~16:9 to match the 1920x1080 card canvas).
const TEXTURE_WIDTH = 2560;
const TEXTURE_HEIGHT = 1440;
const TEXTURE_QUALITY = 82;

// Cream-key: paper background color and tolerance. Pixels within TOL (Euclidean,
// 0..441) of the cream go fully transparent; a FEATHER band above that ramps
// alpha for a soft edge. Cream is the locked palette value #efe8dc.
const CREAM = [0xef, 0xe8, 0xdc];
const KEY_TOL = 60;
const KEY_FEATHER = 22;
// Alpha above which a pixel counts as flower content (for the segmentation mask,
// the per-component bbox, and the min-area test).
const ALPHA_EPS = 12;

// Segmentation tuning (raster pixels, at RASTER_WIDTH). DILATE_RADIUS is the
// square-kernel dilation applied to the content mask BEFORE labeling, to bridge
// gaps where a pale petal was partly cream-keyed so a flower stays ONE component
// (it never fattens the exported art — only the original keyed pixels are kept).
// MIN_AREA drops components with too few original-content pixels (keying specks /
// stray dots) so only real flowers/clusters are exported.
const DILATE_RADIUS = 10;
const MIN_AREA = 5000;

/**
 * Per-slide config: source slide number + the text-safe rectangles (normalized
 * [x0, y0, x1, y1] over the slide) whose pixels are zeroed before segmentation so
 * the SVG's OWN outlined title/body glyphs are never captured as "flowers":
 *   - slide 1 ("Flora.", centered): one central box over the hero title; the
 *     botanicals all sit around the border, clear of it.
 *   - slide 2 ("Definition of Flora.", left): a heading box (both title lines,
 *     including the trailing period) plus a narrower body box under it; the
 *     botanicals are massed down the right, clear of both.
 */
const SLIDES = [
  {
    n: 1,
    textSafe: [[0.26, 0.33, 0.72, 0.66]],
  },
  {
    n: 2,
    textSafe: [
      [0.0, 0.0, 0.58, 0.47],
      [0.0, 0.47, 0.44, 0.9],
    ],
  },
];

const pad2 = (n) => String(n).padStart(2, "0");

/** Decode the embedded paper-texture JPEG from a slide SVG and downscale it to
 *  the shared card background. The texture is identical across slides, so we
 *  read it from slide 1. */
async function extractTexture() {
  const svg = readFileSync(path.join(SLIDES_DIR, "1.svg"), "utf8");
  const m = svg.match(/xlink:href="data:image\/jpeg;base64,([^"]+)"/);
  if (!m) throw new Error("no embedded JPEG found in 1.svg");
  const jpeg = Buffer.from(m[1], "base64");
  const src = sharp(jpeg, { unlimited: true });
  const meta = await src.metadata();
  await src
    .resize(TEXTURE_WIDTH, TEXTURE_HEIGHT, { fit: "cover" })
    .jpeg({ quality: TEXTURE_QUALITY })
    .toFile(path.join(OUT_DIR, "texture.jpg"));
  // Report the mean bg color so the plum/taupe/cream palette can be confirmed.
  const stats = await sharp(jpeg, { unlimited: true }).stats();
  const mean = stats.channels.slice(0, 3).map((c) => Math.round(c.mean));
  console.log(
    `[texture] embedded JPEG ${meta.width}x${meta.height} -> ` +
      `texture.jpg ${TEXTURE_WIDTH}x${TEXTURE_HEIGHT}; mean rgb ~ (${mean.join(
        ", ",
      )}) = #${mean.map((v) => v.toString(16).padStart(2, "0")).join("")}`,
  );
}

/** Cream-key a raw RGBA region in place: transparent where near cream. */
function creamKey(data, count) {
  const [cr, cg, cb] = CREAM;
  for (let i = 0; i < count; i++) {
    const o = i * 4;
    const dr = data[o] - cr;
    const dg = data[o + 1] - cg;
    const db = data[o + 2] - cb;
    const dist = Math.sqrt(dr * dr + dg * dg + db * db);
    if (dist <= KEY_TOL) {
      data[o + 3] = 0;
    } else if (dist < KEY_TOL + KEY_FEATHER) {
      const a = ((dist - KEY_TOL) / KEY_FEATHER) * 255;
      data[o + 3] = Math.min(data[o + 3], Math.round(a));
    }
  }
}

/** Zero alpha inside each normalized text-safe rect, so outlined glyphs there are
 *  removed before segmentation (and can never leak into a flower crop). */
function applyTextMask(data, w, h, rects) {
  for (const [x0, y0, x1, y1] of rects) {
    const px0 = Math.max(0, Math.floor(x0 * w));
    const py0 = Math.max(0, Math.floor(y0 * h));
    const px1 = Math.min(w, Math.ceil(x1 * w));
    const py1 = Math.min(h, Math.ceil(y1 * h));
    for (let y = py0; y < py1; y++) {
      let o = (y * w + px0) * 4 + 3;
      for (let x = px0; x < px1; x++) {
        data[o] = 0;
        o += 4;
      }
    }
  }
}

/** Binary content mask (1 where alpha > ALPHA_EPS) from a keyed RGBA buffer. */
function contentMask(data, w, h) {
  const fg = new Uint8Array(w * h);
  for (let p = 0; p < w * h; p++) {
    if (data[p * 4 + 3] > ALPHA_EPS) fg[p] = 1;
  }
  return fg;
}

/** Dilate a binary mask by a square (2r+1) kernel, separably (h then v). Used to
 *  bridge small gaps so a flower whose pale petals were partly keyed stays one
 *  connected component. Border-clamped; result is a superset of the input, so no
 *  original content pixel is ever dropped from its component. */
function dilate(fg, w, h, r) {
  const tmp = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const x0 = x - r < 0 ? 0 : x - r;
      const x1 = x + r >= w ? w - 1 : x + r;
      let v = 0;
      for (let k = x0; k <= x1; k++) {
        if (fg[row + k]) {
          v = 1;
          break;
        }
      }
      tmp[row + x] = v;
    }
  }
  const out = new Uint8Array(w * h);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      const y0 = y - r < 0 ? 0 : y - r;
      const y1 = y + r >= h ? h - 1 : y + r;
      let v = 0;
      for (let k = y0; k <= y1; k++) {
        if (tmp[k * w + x]) {
          v = 1;
          break;
        }
      }
      out[y * w + x] = v;
    }
  }
  return out;
}

/**
 * 8-connected component labeling of the dilated mask via iterative flood fill.
 * Every component's tight bbox + area are measured over the ORIGINAL content mask
 * (`fg`) only — so the dilation groups pixels but never inflates the exported
 * bbox. Returns the per-pixel `labels` (0 = background) and one record per
 * component.
 */
function labelComponents(dil, fg, w, h) {
  const labels = new Int32Array(w * h);
  const stack = new Int32Array(w * h);
  const comps = [];
  let cur = 0;
  for (let p = 0; p < w * h; p++) {
    if (!dil[p] || labels[p] !== 0) continue;
    cur += 1;
    let sp = 0;
    stack[sp++] = p;
    labels[p] = cur;
    let minX = w;
    let minY = h;
    let maxX = -1;
    let maxY = -1;
    let area = 0;
    while (sp > 0) {
      const q = stack[--sp];
      const qy = (q / w) | 0;
      const qx = q - qy * w;
      if (fg[q]) {
        if (qx < minX) minX = qx;
        if (qx > maxX) maxX = qx;
        if (qy < minY) minY = qy;
        if (qy > maxY) maxY = qy;
        area += 1;
      }
      for (let dy = -1; dy <= 1; dy++) {
        const ny = qy + dy;
        if (ny < 0 || ny >= h) continue;
        for (let dx = -1; dx <= 1; dx++) {
          if (dx === 0 && dy === 0) continue;
          const nx = qx + dx;
          if (nx < 0 || nx >= w) continue;
          const np = ny * w + nx;
          if (dil[np] && labels[np] === 0) {
            labels[np] = cur;
            stack[sp++] = np;
          }
        }
      }
    }
    comps.push({ id: cur, minX, minY, maxX, maxY, area });
  }
  return { labels, comps };
}

/** Remove previously-generated PNGs for a slide, so a re-run leaves only the
 *  current per-flower set (no stale rectangle crops). */
function cleanSlide(n) {
  const prefix = `slide${pad2(n)}-`;
  for (const f of readdirSync(BOTANICALS_DIR)) {
    if (f.startsWith(prefix) && f.endsWith(".png")) {
      unlinkSync(path.join(BOTANICALS_DIR, f));
    }
  }
}

async function extractSlide(slide, w, h, data) {
  applyTextMask(data, w, h, slide.textSafe);
  const fg = contentMask(data, w, h);
  const dil = dilate(fg, w, h, DILATE_RADIUS);
  const { labels, comps } = labelComponents(dil, fg, w, h);

  // Keep real flowers/clusters only, in reading order (top-to-bottom, then
  // left-to-right) for stable, meaningful filenames.
  const kept = comps
    .filter((c) => c.area >= MIN_AREA && c.maxX >= 0)
    .sort((a, b) => a.minY - b.minY || a.minX - b.minX);

  cleanSlide(slide.n);

  const entries = [];
  let k = 0;
  for (const c of kept) {
    k += 1;
    const bw = c.maxX - c.minX + 1;
    const bh = c.maxY - c.minY + 1;
    // Copy ONLY this component's original keyed pixels into a tight buffer;
    // pixels belonging to other components (labels !== id) are left transparent,
    // so overlapping bboxes never bleed one flower into another's crop.
    const out = Buffer.alloc(bw * bh * 4);
    for (let y = 0; y < bh; y++) {
      for (let x = 0; x < bw; x++) {
        const sp = (c.minY + y) * w + (c.minX + x);
        if (labels[sp] === c.id) {
          const so = sp * 4;
          const dp = (y * bw + x) * 4;
          out[dp] = data[so];
          out[dp + 1] = data[so + 1];
          out[dp + 2] = data[so + 2];
          out[dp + 3] = data[so + 3];
        }
      }
    }

    const file = `slide${pad2(slide.n)}-${pad2(k)}.png`;
    await sharp(out, { raw: { width: bw, height: bh, channels: 4 } })
      .png()
      .toFile(path.join(BOTANICALS_DIR, file));

    const bbox = {
      x: +(c.minX / w).toFixed(4),
      y: +(c.minY / h).toFixed(4),
      w: +(bw / w).toFixed(4),
      h: +(bh / h).toFixed(4),
    };
    entries.push({ file, sourceSlide: slide.n, bbox });
    console.log(
      `[slide${slide.n}] ${file}  ${bw}x${bh}px  area=${c.area}  bbox=` +
        `{x:${bbox.x}, y:${bbox.y}, w:${bbox.w}, h:${bbox.h}}`,
    );
  }
  console.log(`[slide${slide.n}] ${entries.length} flowers from ${comps.length} components`);
  return entries;
}

async function main() {
  mkdirSync(BOTANICALS_DIR, { recursive: true });

  await extractTexture();

  const botanicals = [];
  for (const slide of SLIDES) {
    // Rasterize the whole slide to a flat RGBA buffer, cream-key it, then segment.
    const { data, info } = await sharp(
      path.join(SLIDES_DIR, `${slide.n}.svg`),
      { density: RASTER_DENSITY, unlimited: true },
    )
      .resize(RASTER_WIDTH)
      .ensureAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    console.log(`[slide${slide.n}] raster ${info.width}x${info.height}`);
    creamKey(data, info.width * info.height);
    const entries = await extractSlide(slide, info.width, info.height, data);
    botanicals.push(...entries);
  }

  const manifest = {
    texture: "texture.jpg",
    textureSize: { w: TEXTURE_WIDTH, h: TEXTURE_HEIGHT },
    cream: `#${CREAM.map((v) => v.toString(16).padStart(2, "0")).join("")}`,
    // Each botanical is one segmented flower (or a cluster of touching flowers);
    // bbox is its normalized position over the 1440x810 slide (== the 16:9 raster).
    botanicals,
  };
  writeFileSync(
    path.join(OUT_DIR, "manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );
  console.log(
    `[done] ${botanicals.length} botanicals + texture.jpg + manifest.json in ${OUT_DIR}`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
