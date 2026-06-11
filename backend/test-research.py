from services.research_service import (
    generate_research,
    save_research,
    slugify
)

topic = "Why the 2026 World Cup is a Mess"

project_name = slugify(topic)

research = generate_research(topic)

save_research(
    project_name,
    {
        "topic": topic,
        "research": research
    }
)

print("Research saved!")