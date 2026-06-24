"""Visual-prompt enhancement standalone runner.

Reads scene_plan.json + channel visuals config, calls the enhancer (or falls
back to passthrough), writes visual_prompts.json.

    python run_visual_prompts.py <project_name>
"""

import sys

from services.visual_prompt_service import (
    generate_visual_prompts,
    save_visual_prompts,
)


def run_visual_prompts(project_name: str):
    payload = generate_visual_prompts(project_name)
    path = save_visual_prompts(project_name, payload)
    print(
        f"  Wrote {payload.get('source', '?')} prompts for "
        f"{len(payload.get('scenes', []))} scenes -> {path}",
        flush=True,
    )
    return payload


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_visual_prompts(sys.argv[1])
