import { readdir } from "node:fs/promises";
import path from "node:path";

import { NextResponse } from "next/server";

/**
 * Lists the downloaded Lottie animations the /remotion "Lottie Library" tab
 * curates. They live in `public/lottie/`, so Next already serves each file at
 * `/lottie/<name>` — this route just enumerates them.
 *
 * Node runtime + force-dynamic: it reads the filesystem on every request so a
 * freshly dropped-in .json shows up on refresh (no build-time snapshot).
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LOTTIE_DIR = path.join(process.cwd(), "public", "lottie");

export async function GET() {
  let names: string[] = [];
  try {
    const entries = await readdir(LOTTIE_DIR);
    names = entries
      .filter((n) => n.toLowerCase().endsWith(".json"))
      .sort((a, b) => a.localeCompare(b));
  } catch {
    // Directory absent (nothing downloaded yet) → empty library.
  }
  return NextResponse.json(
    names.map((name) => ({ name, url: `/lottie/${name}` })),
  );
}
