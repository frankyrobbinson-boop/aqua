from dotenv import load_dotenv
import json
import os
import re
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)



def generate_research(topic: str):
    response = client.responses.create(
        model="gpt-5",
        input=f"""
        Research this topic:

        {topic}
        """
    )

    return response.output_text

def save_research(project_name, content):

    folder = f"../projects/{project_name}"

    os.makedirs(folder, exist_ok=True)

    with open(
        f"{folder}/research.json",
        "w"
    ) as f:
        json.dump(content, f, indent=2)

def load_research(project_name):
    with open(
        f"../projects/{project_name}/research.json",
        "r"
    ) as f:
        return json.load(f)



def slugify(text):

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text
    )

    result = text.strip("-")
    if not result:
        raise ValueError(
            "Topic produces an empty project name; "
            "use a topic with at least one letter or digit"
        )
    return result