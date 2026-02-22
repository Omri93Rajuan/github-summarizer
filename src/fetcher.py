"""
Fetches and filters GitHub repository content via the GitHub REST API.

Strategy:
  1. Always include the root directory tree (structural overview).
  2. Read high-signal files first: README, manifests, Dockerfiles, etc.
  3. Skip low-signal content: binaries, lock files, generated dirs.
  4. Hard-cap total context at MAX_CONTEXT_CHARS to stay within LLM limits.
"""

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# ── filtering ─────────────────────────────────────────────────────────────────

SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".pytest_cache",
    "venv", ".venv", "env", "dist", "build", ".next", ".nuxt",
    "coverage", ".tox", ".eggs", "htmlcov",
    ".mypy_cache", ".ruff_cache", "vendor",
})

SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3",
    ".zip", ".tar", ".gz", ".bin", ".exe", ".dll", ".so",
    ".dylib", ".pyc", ".pyo", ".map", ".pdf",
})

SKIP_FILENAMES: frozenset[str] = frozenset({
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
    "pnpm-lock.yaml", "composer.lock", "Gemfile.lock",
    ".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes",
})

# Read these first — they carry the most signal about a project
PRIORITY_FILES: list[str] = [
    "README.md", "README.rst", "README.txt", "README",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "Cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "requirements.txt", "Makefile",
    ".env.example",
]

MAX_CONTEXT_CHARS = 60_000   # ~15k tokens — safe for most models
MAX_FILE_CHARS    = 8_000    # cap per individual file


# ── helpers ───────────────────────────────────────────────────────────────────

def _should_skip(path: str) -> bool:
    """Return True if the path should be excluded from context."""
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return True
    filename = parts[-1]
    if filename in SKIP_FILENAMES:
        return True
    return any(filename.endswith(ext) for ext in SKIP_EXTENSIONS)


def _parse_owner_repo(github_url: str) -> tuple[str, str]:
    tail = github_url.removeprefix("https://github.com/").rstrip("/")
    owner, repo = tail.split("/", 1)
    return owner, repo


# ── main fetcher ──────────────────────────────────────────────────────────────

@dataclass
class RepoContext:
    owner: str
    repo: str
    sections: list[str] = field(default_factory=list)
    _total_chars: int = 0

    def add(self, header: str, content: str) -> bool:
        """Append a section. Returns False if context limit reached."""
        if self._total_chars >= MAX_CONTEXT_CHARS:
            return False
        body = content[:MAX_FILE_CHARS]
        entry = f"=== {header} ===\n{body}\n\n"
        self.sections.append(entry)
        self._total_chars += len(entry)
        return True

    def render(self) -> str:
        return "".join(self.sections)[:MAX_CONTEXT_CHARS]


async def fetch_repo_context(github_url: str) -> str:
    """
    Fetch repo content from the GitHub API and return a
    context string ready to send to the LLM.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx responses (e.g. 404 private/missing repo)
        httpx.RequestError: on network-level failures
    """
    owner, repo = _parse_owner_repo(github_url)
    ctx = RepoContext(owner=owner, repo=repo)

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:

        # 1. Root tree — always include for structural overview
        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
        )
        tree_resp.raise_for_status()
        tree_data = tree_resp.json()

        all_paths: list[str] = [
            item["path"]
            for item in tree_data.get("tree", [])
            if item["type"] == "blob"
        ]

        readable_tree = "\n".join(
            p for p in all_paths if not _should_skip(p)
        )
        ctx.add("DIRECTORY TREE (filtered)", readable_tree)

        # 2. Priority files first
        for filename in PRIORITY_FILES:
            if ctx._total_chars >= MAX_CONTEXT_CHARS:
                break
            if filename not in all_paths:
                continue
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}"
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            # GitHub returns base64-encoded content
            import base64
            try:
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            except Exception:
                continue
            ctx.add(filename, content)

        # 3. Fill remaining budget with other source files (by path length — shorter = higher level)
        remaining_files = sorted(
            (p for p in all_paths if not _should_skip(p) and p not in PRIORITY_FILES),
            key=lambda p: (p.count("/"), len(p)),
        )
        for path in remaining_files:
            if ctx._total_chars >= MAX_CONTEXT_CHARS:
                break
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            import base64
            try:
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            except Exception:
                continue
            ctx.add(path, content)

    result = ctx.render()
    if not result.strip():
        raise ValueError("Repository appears to be empty or has no readable files.")

    logger.info(
        "Gathered repo context for %s/%s: %d chars across %d sections",
        owner, repo, len(result), len(ctx.sections),
    )
    return result
