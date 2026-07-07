import { unlink } from "node:fs/promises";
import path from "node:path";

import { NextResponse } from "next/server";

/**
 * Removes one Lottie the user doesn't want from `public/lottie/`. The library
 * tab calls this when the trash button is clicked, then refetches the list.
 *
 * `name` is a URL segment, so it is validated hard: it must be a plain
 * `*.json` basename. Anything with a path separator or `..` is rejected before
 * it touches the filesystem — no traversal out of the lottie directory.
 */
export const runtime = "nodejs";

const LOTTIE_DIR = path.join(process.cwd(), "public", "lottie");

function isSafeLottieName(name: string): boolean {
  return (
    name.length > 0 &&
    !name.includes("/") &&
    !name.includes("\\") &&
    !name.includes("..") &&
    path.basename(name) === name &&
    name.toLowerCase().endsWith(".json")
  );
}

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  if (!isSafeLottieName(name)) {
    return NextResponse.json({ error: "Invalid name" }, { status: 400 });
  }
  try {
    await unlink(path.join(LOTTIE_DIR, name));
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }
    throw err;
  }
  return NextResponse.json({ ok: true });
}
