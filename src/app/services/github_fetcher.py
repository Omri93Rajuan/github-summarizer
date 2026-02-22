"""
Fetch and filter GitHub repository content via the GitHub REST API.
"""

import base64
import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        ".tox",
        ".eggs",
        "htmlcov",
        ".mypy_cache",
        ".ruff_cache",
        "vendor",
    }
)

SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".lock",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp4",
        ".mp3",
        ".zip",
        ".tar",
        ".gz",
        ".bin",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".map",
        ".pdf",
    }
)

SKIP_FILENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "Gemfile.lock",
        ".DS_Store",
        "Thumbs.db",
        ".gitignore",
        ".gitattributes",
    }
)

PRIORITY_FILES: list[str] = [
    "README.md",
    "README.rst",
    "README.txt",
    "README",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "requirements.txt",
    "Makefile",
    ".env.example",
]

MAX_CONTEXT_CHARS = 60_000
MAX_FILE_CHARS = 8_000
MAX_FILE_REQUESTS = 40
MAX_API_CALLS = 60

SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".cs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".md",
        ".rst",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        ".env",
        ".sh",
        ".ps1",
    }
)

PRIORITY_DIR_PREFIXES: tuple[str, ...] = (
    "src/",
    "app/",
    "lib/",
    "packages/",
    "cmd/",
    "internal/",
    "server/",
    "client/",
)


def _should_skip(path: str) -> bool:
    parts = path.split("/")
    if any(part in SKIP_DIRS for part in parts):
        return True
    filename = parts[-1]
    if filename in SKIP_FILENAMES:
        return True
    return any(filename.endswith(ext) for ext in SKIP_EXTENSIONS)


def _parse_owner_repo(github_url: str) -> tuple[str, str]:
    tail = github_url.removeprefix("https://github.com/").rstrip("/")
    owner, repo = tail.split("/", 1)
    return owner, repo


def _is_likely_source_file(path: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return filename in {"Dockerfile", "Makefile", "Jenkinsfile"}
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return ext in SOURCE_EXTENSIONS


def _path_rank(path: str) -> tuple[int, int, int]:
    rank = 1
    if path.startswith(PRIORITY_DIR_PREFIXES):
        rank = 0
    return (rank, path.count("/"), len(path))


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        return True
    return False


async def _fetch_file_content(client: httpx.AsyncClient, url: str) -> tuple[str | None, bool]:
    response = await client.get(url)
    if _is_rate_limited(response):
        return None, True
    if response.status_code != 200:
        return None, False

    data = response.json()
    if data.get("encoding") != "base64":
        return None, False
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None, False
    return content, False


@dataclass
class RepoContext:
    owner: str
    repo: str
    sections: list[str] = field(default_factory=list)
    total_chars: int = 0

    def add(self, header: str, content: str) -> bool:
        if self.total_chars >= MAX_CONTEXT_CHARS:
            return False
        body = content[:MAX_FILE_CHARS]
        entry = f"=== {header} ===\n{body}\n\n"
        self.sections.append(entry)
        self.total_chars += len(entry)
        return True

    def render(self) -> str:
        return "".join(self.sections)[:MAX_CONTEXT_CHARS]


async def fetch_repo_context(github_url: str) -> str:
    owner, repo = _parse_owner_repo(github_url)
    ctx = RepoContext(owner=owner, repo=repo)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
        api_calls = 0
        file_requests = 0

        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
        )
        api_calls += 1
        tree_resp.raise_for_status()
        tree_data = tree_resp.json()

        all_paths: list[str] = [
            item["path"] for item in tree_data.get("tree", []) if item["type"] == "blob"
        ]

        readable_tree = "\n".join(path for path in all_paths if not _should_skip(path))
        ctx.add("DIRECTORY TREE (filtered)", readable_tree)

        rate_limited = False

        for filename in PRIORITY_FILES:
            if ctx.total_chars >= MAX_CONTEXT_CHARS or file_requests >= MAX_FILE_REQUESTS or api_calls >= MAX_API_CALLS:
                break
            if filename not in all_paths:
                continue

            content, limited = await _fetch_file_content(
                client,
                f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}",
            )
            api_calls += 1
            file_requests += 1
            if limited:
                rate_limited = True
                logger.warning("GitHub rate limit hit while fetching priority file: %s", filename)
                break
            if content is None:
                continue
            ctx.add(filename, content)

        remaining_files = sorted(
            (
                path
                for path in all_paths
                if not _should_skip(path)
                and path not in PRIORITY_FILES
                and _is_likely_source_file(path)
            ),
            key=_path_rank,
        )

        for path in remaining_files:
            if rate_limited:
                break
            if (
                ctx.total_chars >= MAX_CONTEXT_CHARS
                or file_requests >= MAX_FILE_REQUESTS
                or api_calls >= MAX_API_CALLS
            ):
                break

            content, limited = await _fetch_file_content(
                client,
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            )
            api_calls += 1
            file_requests += 1
            if limited:
                rate_limited = True
                logger.warning("GitHub rate limit hit while fetching file: %s", path)
                break
            if content is None:
                continue
            ctx.add(path, content)

    result = ctx.render()
    if not result.strip():
        raise ValueError("Repository appears to be empty or has no readable files.")

    logger.info(
        "Gathered repo context for %s/%s: %d chars across %d sections (api_calls=%d file_requests=%d)",
        owner,
        repo,
        len(result),
        len(ctx.sections),
        api_calls,
        file_requests,
    )
    return result
