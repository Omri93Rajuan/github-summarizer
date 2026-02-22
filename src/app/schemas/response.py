from pydantic import BaseModel


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str

