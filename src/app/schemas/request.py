from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class SummarizeRequest(BaseModel):
    github_url: str

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, value: str) -> str:
        raw = value.strip()
        parsed = urlparse(raw)

        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise ValueError("URL must start with https://github.com/")

        segments = [part for part in parsed.path.strip("/").split("/") if part]
        if len(segments) < 2:
            raise ValueError("URL must be in the format https://github.com/owner/repo")

        owner, repo = segments[0], segments[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not owner or not repo:
            raise ValueError("URL must be in the format https://github.com/owner/repo")

        return f"https://github.com/{owner}/{repo}"
