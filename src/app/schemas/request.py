from pydantic import BaseModel, field_validator


class SummarizeRequest(BaseModel):
    github_url: str

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("https://github.com/"):
            raise ValueError("URL must start with https://github.com/")
        parts = value.rstrip("/").removeprefix("https://github.com/").split("/")
        if len(parts) < 2 or not all(parts):
            raise ValueError("URL must be in the format https://github.com/owner/repo")
        return value.rstrip("/")

