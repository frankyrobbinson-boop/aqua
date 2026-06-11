from fastapi import FastAPI
from services.research_service import generate_research, save_research, slugify

app = FastAPI()

@app.get("/")
def root():
    return {"status": "working"}


@app.post("/research")
def research(topic: str):
    project_name = slugify(topic)
    result = generate_research(topic)
    save_research(project_name, {"topic": topic, "research": result})
    return result