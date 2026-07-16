/**
 * build-phosphor-index.mjs — generate backend/data/phosphor_index.json, the
 * tag/category metadata the backend icon resolver searches over.
 *
 * INTENTIONAL SPLIT (see project memory "Image model" / the icon plan):
 *   - The SVG FILES we ship live in frontend/public/icons/phosphor/regular/ and
 *     were staged from ~/Downloads/phosphor-icons/SVGs/regular/ — the stroked /
 *     outline style that matches the 4 proven icons already in the pipeline.
 *   - The TAGS + CATEGORIES come from the npm package @phosphor-icons/core, whose
 *     metadata `name` equals the Downloads SVG basename for 1511/1512 icons.
 *   The npm package also ships its OWN assets/regular/*.svg, but those are a
 *   DIFFERENT (filled single-path) look — we never stage them, only read their
 *   metadata. Files from Downloads, tags from npm.
 *
 * CROSS-WORKSPACE WRITE: this script lives in the frontend workspace but writes
 * its output into the BACKEND workspace (../../backend/data/phosphor_index.json)
 * because the resolver that consumes it is Python. The staged SVG directory is
 * the authoritative list of icons; an icon only appears in the index if its SVG
 * is actually staged (so the resolver can never point at a missing glyph).
 *
 * Run:  npm run build:phosphor-index      (from frontend/)
 * FREE / offline — no API calls. Safe to re-run; output is deterministic.
 */
import { readdirSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { icons } from "@phosphor-icons/core";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Authoritative staged SVGs (files from Downloads) and the backend output path.
const STAGED_DIR = path.resolve(__dirname, "../public/icons/phosphor/regular");
const OUT_PATH = path.resolve(__dirname, "../../backend/data/phosphor_index.json");

/** Drop `*new*` / `*updated*` style noise tokens and trim; keep the rest. */
function cleanTokens(list) {
  const out = [];
  for (const raw of list ?? []) {
    const t = String(raw).trim();
    if (!t) continue;
    if (/^\*.*\*$/.test(t)) continue; // *new*, *updated*, ...
    out.push(t);
  }
  return out;
}

function main() {
  // Metadata universe keyed by the icon's primary `name` (1512 entries). This
  // set — NOT the alias names — is what the metadata-without-file check reports.
  const byName = new Map();
  // Defensive fallback: if a staged basename ever matches an icon's `alias.name`
  // rather than its primary name, we still find its metadata. (Today no staged
  // file needs this, but it keeps the split robust.)
  const byAlias = new Map();
  for (const icon of icons) {
    const meta = {
      tags: cleanTokens(icon.tags),
      categories: cleanTokens(icon.categories),
    };
    byName.set(icon.name, meta);
    if (icon.alias && icon.alias.name) byAlias.set(icon.alias.name, meta);
  }

  // Staged basenames are authoritative — read the actual shipped SVG files.
  const staged = readdirSync(STAGED_DIR)
    .filter((f) => f.endsWith(".svg"))
    .map((f) => f.slice(0, -".svg".length))
    .sort();

  const index = {};
  const stagedWithoutMetadata = [];
  let matched = 0;
  for (const name of staged) {
    const meta = byName.get(name) ?? byAlias.get(name);
    if (meta) {
      index[name] = { tags: meta.tags, categories: meta.categories };
      matched += 1;
    } else {
      // No metadata (the book-user case): still ship the icon, empty arrays.
      index[name] = { tags: [], categories: [] };
      stagedWithoutMetadata.push(name);
    }
  }

  // Metadata (primary names) with no staged SVG file — expect only book-open-user.
  const stagedSet = new Set(staged);
  const metadataWithoutFile = [...byName.keys()].filter((n) => !stagedSet.has(n)).sort();

  // Keys are the sorted staged basenames; 2-space indent, trailing newline.
  const sorted = {};
  for (const k of Object.keys(index).sort()) sorted[k] = index[k];
  mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  writeFileSync(OUT_PATH, JSON.stringify(sorted, null, 2) + "\n");

  console.log("[phosphor-index] wrote", OUT_PATH);
  console.log("[phosphor-index] ---- reconciliation ----");
  console.log(`[phosphor-index] staged SVGs (total):      ${staged.length}`);
  console.log(`[phosphor-index] matched to metadata:      ${matched}`);
  console.log(
    `[phosphor-index] staged WITHOUT metadata:   ${stagedWithoutMetadata.length}` +
      (stagedWithoutMetadata.length ? ` -> ${stagedWithoutMetadata.join(", ")}` : ""),
  );
  console.log(
    `[phosphor-index] metadata WITHOUT file:     ${metadataWithoutFile.length}` +
      (metadataWithoutFile.length ? ` -> ${metadataWithoutFile.join(", ")}` : ""),
  );
  console.log("[phosphor-index] Done.");
}

main();
