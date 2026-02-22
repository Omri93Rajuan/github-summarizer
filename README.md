# GitHub Repository Summarizer

A FastAPI service that accepts a GitHub repository URL and returns a structured, human-readable summary — what the project does, which technologies it uses, and how it is organized.

Built with **Python 3.10+**, **LangChain**, and **Nebius Token Factory** (Llama 3.1 70B).

---

## Setup & Run

### Prerequisites

- Python 3.10+

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set the API key

```bash
export NEBIUS_API_KEY="your_nebius_api_key_here"
```

Windows (PowerShell):
```powershell
$env:NEBIUS_API_KEY="your_nebius_api_key_here"
```

### 3. Start the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. Test it

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

Expected response:
```json
{
  "summary": "Requests is a widely-used Python HTTP library...",
  "technologies": ["Python", "urllib3", "certifi", "charset-normalizer"],
  "structure": "Standard Python package layout with source in src/requests/, tests in tests/, and documentation in docs/."
}
```

Error responses include an HTTP status code and:
```json
{ "status": "error", "message": "..." }
```

---

## Design Decisions

### Model
**`meta-llama/Meta-Llama-3.1-70B-Instruct`** via Nebius Token Factory.  
Strong instruction-following and reliable structured JSON output; handles technical/code content well.

### How repository content is handled

Fetching uses the **GitHub REST API** (no extra tools required). Content is assembled in three steps:

**1. Filter aggressively (`src/fetcher.py`)**  
Skip anything that adds noise without insight:
- Binary files (images, fonts, compiled artifacts)
- Dependency lock files (`package-lock.json`, `yarn.lock`, `poetry.lock`, etc.) — verbose and redundant with manifest files
- Generated/build directories (`dist/`, `build/`, `node_modules/`, `__pycache__/`, etc.)
- IDE/OS metadata (`.DS_Store`, `.gitignore`, etc.)

**2. Prioritize high-signal files**  
Read in this order until the context budget is used:
- `README.md` / `README.rst` — the single best summary of any project
- Manifest files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`) — reveal language, dependencies, and scripts
- `Dockerfile` / `docker-compose.yml` — expose deployment context and services
- `requirements.txt`, `Makefile` — additional technical context

**3. Stay within context limits**  
- Hard cap: **60,000 characters** (~15k tokens) total
- Per-file cap: **8,000 characters** — long files are truncated, not excluded
- Remaining budget is filled with other source files ordered by directory depth (shallow files first)
- The filtered directory tree is always included first to give the LLM structural awareness

### Architecture

```
POST /summarize
    └── FastAPI  (main.py)
        ├── Input validation          (src/models.py  — Pydantic)
        ├── Repository fetching       (src/fetcher.py — GitHub REST API + httpx)
        └── LLM summarization         (src/agent.py   — LangChain + Nebius)
```
