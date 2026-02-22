# GitHub Repository Summarizer

Tiny FastAPI service that gets a public GitHub repo URL and returns:
- what the project does
- main technologies
- a short structure overview

## Quick start

Requirements: Python 3.10+

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Set API key:

```bash
export NEBIUS_API_KEY="your_key"
```

Windows PowerShell:

```powershell
$env:NEBIUS_API_KEY="your_key"
```

Optional (recommended for large repositories to avoid GitHub rate limits):

```bash
export GITHUB_TOKEN="your_github_token"
```

Run server:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

Test endpoint:

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url":"https://github.com/psf/requests"}'
```

## Endpoint

`POST /summarize`

Request:

```json
{ "github_url": "https://github.com/psf/requests" }
```

Response:

```json
{
  "summary": "...",
  "technologies": ["Python", "..."],
  "structure": "..."
}
```

Error format:

```json
{ "status": "error", "message": "..." }
```

## Model choice

I used `openai/gpt-oss-120b` via Nebius.
It gives stable structured JSON output and good code understanding for this task.

## Repo processing approach

Since repos can be big, I do this:
- always include filtered directory tree first
- prioritize high-signal files (README, manifests, Dockerfiles, requirements, Makefile)
- skip noisy content (binaries, lock files, `node_modules`, `dist`, `build`, caches)
- cap total context and per-file size so requests stay within LLM limits

## Tests

```bash
pytest -q
```
