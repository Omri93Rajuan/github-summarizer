from pydantic import BaseModel, HttpUrl, field_validator


class SummarizeRequest(BaseModel):
    github_url: str

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://github.com/"):
            raise ValueError("URL must start with https://github.com/")
        parts = v.rstrip("/").removeprefix("https://github.com/").split("/")
        if len(parts) < 2 or not all(parts):
            raise ValueError("URL must be in the format https://github.com/owner/repo")
        return v.rstrip("/")


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
