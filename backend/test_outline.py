from services.outline_service import generate_outline, save_outline

project_name = "why-the-2026-world-cup-is-a-mess"


outline = generate_outline(project_name)

save_outline(project_name, outline)