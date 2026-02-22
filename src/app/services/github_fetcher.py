"""
Fetch and filter GitHub repository content via a single archive download.
"""

import io
import logging
import os
import zipfile
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
MAX_FILES_TO_READ = 80
MAX_ARCHIVE_BYTES = 40_000_000
MAX_FILE_READ_BYTES = 200_000

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


def _strip_archive_root(path: str) -> str:
    if "/" not in path:
        return path
    return path.split("/", 1)[1]


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
        "Accept": "application/vnd.github+json, application/zip",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-summarizer-app",
    }
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
        archive_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/zipball")
        if _is_rate_limited(archive_resp):
            archive_resp.raise_for_status()
        archive_resp.raise_for_status()

        archive_bytes = archive_resp.content
        if len(archive_bytes) > MAX_ARCHIVE_BYTES:
            raise ValueError("Repository archive is too large to summarize with current limits.")

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            path_to_info: dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                if info.is_dir():
                    continue
                logical_path = _strip_archive_root(info.filename)
                if not logical_path or _should_skip(logical_path):
                    continue
                path_to_info[logical_path] = info

            all_paths = sorted(path_to_info.keys())
            ctx.add("DIRECTORY TREE (filtered)", "\n".join(all_paths))

            files_read = 0
            all_paths_set = set(all_paths)

            for filename in PRIORITY_FILES:
                if ctx.total_chars >= MAX_CONTEXT_CHARS or files_read >= MAX_FILES_TO_READ:
                    break
                if filename not in all_paths_set:
                    continue
                info = path_to_info[filename]
                try:
                    with archive.open(info) as file_handle:
                        content = file_handle.read(MAX_FILE_READ_BYTES).decode("utf-8", errors="replace")
                except Exception:
                    continue
                ctx.add(filename, content)
                files_read += 1

            remaining_files = sorted(
                (
                    path
                    for path in all_paths
                    if path not in PRIORITY_FILES and _is_likely_source_file(path)
                ),
                key=_path_rank,
            )

            for path in remaining_files:
                if ctx.total_chars >= MAX_CONTEXT_CHARS or files_read >= MAX_FILES_TO_READ:
                    break
                info = path_to_info[path]
                try:
                    with archive.open(info) as file_handle:
                        content = file_handle.read(MAX_FILE_READ_BYTES).decode("utf-8", errors="replace")
                except Exception:
                    continue
                ctx.add(path, content)
                files_read += 1

    result = ctx.render()
    if not result.strip():
        raise ValueError("Repository appears to be empty or has no readable files.")

    logger.info(
        "Gathered repo context for %s/%s: %d chars across %d sections",
        owner,
        repo,
        len(result),
        len(ctx.sections),
    )
    return result
