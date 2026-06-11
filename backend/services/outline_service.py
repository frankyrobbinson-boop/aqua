from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re
from services.research_service import load_research

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

def load_outline_prompt():
    with open(
        "prompts/outline.md",
        "r"
    ) as f:
        return f.read()

def generate_outline(project_name):

    research = load_research(project_name)
    prompt = load_outline_prompt()

    response = client.responses.create(
        model="gpt-5",
        input=f"""
{prompt}

RESEARCH:
{research["research"]}
"""
    )

    text = response.output_text.strip()
    # Strip markdown code fences that models sometimes wrap around JSON output
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)

    return json.loads(text.strip())
    
def save_outline(project_name, outline):

    folder = f"../projects/{project_name}"

    os.makedirs(folder, exist_ok=True)

    with open(f"{folder}/outline.json", "w") as f:
        json.dump(outline, f, indent=2)

def load_outline(project_name):
    with open(
        f"../projects/{project_name}/outline.json",
        "r"
    ) as f:
        return json.load(f)