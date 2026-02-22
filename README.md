# GitHub Repository Summarizer

A FastAPI service that accepts a GitHub repository URL and returns a structured, human-readable summary: what the project does, which technologies it uses, and how it is organized.

Built with **Python 3.10+**, **LangChain**, and **Nebius**.

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
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

Backward-compatible entrypoint still works:

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

### 5. Run tests

```bash
pytest -q
```

---

## Project Structure

```text
src/
  app/
    main.py
    api/
      routes.py
    services/
      github_fetcher.py
      summarizer.py
    schemas/
      request.py
      response.py
      error.py
    core/
      config.py
      logging.py
```

---

## Design Notes

### Model

`openai/gpt-oss-120b` via Nebius.

### Repository content strategy

1. Filter aggressively (`src/app/services/github_fetcher.py`)
- Skips binary files, lock files, generated/build directories, and metadata noise.

2. Prioritize high-signal files
- Reads README, manifest files, Docker files, and requirements first.

3. Keep context bounded
- Hard cap: `60,000` chars
- Per-file cap: `8,000` chars
- Remaining budget is filled with source files ordered by path depth.

### Request flow

`POST /summarize` -> FastAPI route -> GitHub fetcher service -> LLM summarizer service -> structured JSON response.
