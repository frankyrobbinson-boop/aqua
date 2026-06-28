"""Generate the per-scene Edit Decision List (edl.json) for a project.

Sits between run_visuals.py (footage fetch) and run_render.py (assembly).
The EDL is a per-scene config map the renderer reads — V1 ships listicle
text overlays and forward-compatible transition/ken_burns slots.

Usage::

    python run_edit.py <project_name>

Per-render defaults come from the same env vars run_render.py honors so the
Render tab's choices flow through unchanged when the EDL is generated at
render time::

    RENDER_TRANSITION=cut|fade   (default: cut)
    RENDER_KEN_BURNS=0|1         (default: 0)
"""

import os
import sys

from services.edl_service import generate_default_edl, save_edl


def run_edit(
    project_name: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> dict:
    if transition not in ("cut", "fade"):
        print(f"  WARN: transition={transition!r} invalid, falling back to 'cut'")
        transition = "cut"
    print("[[STAGE:edl:started]]", flush=True)
    edl = generate_default_edl(
        project_name, transition=transition, ken_burns=ken_burns,
    )
    save_edl(project_name, edl)
    print(f"  edl.json saved ({len(edl['scenes'])} scenes)")
    print("[[STAGE:edl:completed]]", flush=True)
    return edl


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_edit(
        sys.argv[1],
        transition=os.environ.get("RENDER_TRANSITION", "cut"),
        ken_burns=os.environ.get("RENDER_KEN_BURNS", "0") == "1",
    )
