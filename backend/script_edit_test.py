from services.script_edit_service import (
    load_script_draft,
    load_script_edit_prompt
)

project_name = (
    "everything-wrong-with-the-2026-world-cup"
)

draft = load_script_draft(
    project_name
)

prompt = load_script_edit_prompt()

print(type(draft))
print(prompt[:200])