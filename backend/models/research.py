from pydantic import BaseModel

class ResearchResult(BaseModel):
    topic: str
    summary: str
    facts: list[str]
    statistics: list[str]
    angles: list[str]