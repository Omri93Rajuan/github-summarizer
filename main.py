import logging
import os

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.agent import run_summarize_chain
from src.fetcher import fetch_repo_context
from src.models import ErrorResponse, SummarizeRequest, SummarizeResponse

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="GitHub Repository Summarizer",
    description="Returns a human-readable summary of any public GitHub repository.",
    version="1.0.0",
)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


# ── endpoint ──────────────────────────────────────────────────────────────────

@app.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def summarize(request: Request) -> JSONResponse | SummarizeResponse:
    # --- parse & validate request body ---
    try:
        body = await request.json()
    except Exception:
        return _error("Request body must be valid JSON.", status.HTTP_400_BAD_REQUEST)

    try:
        payload = SummarizeRequest(**body)
    except ValidationError as exc:
        messages = "; ".join(e["msg"] for e in exc.errors())
        return _error(messages, status.HTTP_400_BAD_REQUEST)

    github_url = payload.github_url
    logger.info("Summarize request for: %s", github_url)

    # --- fetch repository content ---
    try:
        context = await fetch_repo_context(github_url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return _error(
                f"Repository not found: '{github_url}'. Make sure it is public and the URL is correct.",
                status.HTTP_404_NOT_FOUND,
            )
        if exc.response.status_code == 403:
            return _error(
                "GitHub API rate limit exceeded. Please try again later.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        logger.exception("GitHub API error for %s", github_url)
        return _error(f"GitHub API error: {exc.response.status_code}", status.HTTP_502_BAD_GATEWAY)
    except httpx.RequestError as exc:
        logger.exception("Network error fetching %s", github_url)
        return _error(f"Network error while contacting GitHub: {exc}", status.HTTP_502_BAD_GATEWAY)
    except ValueError as exc:
        return _error(str(exc), status.HTTP_400_BAD_REQUEST)

    # --- run LLM chain ---
    try:
        result = await run_summarize_chain(github_url, context)
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        return _error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    except ValueError as exc:
        logger.exception("LLM parsing error for %s", github_url)
        return _error(f"Failed to parse LLM response: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        logger.exception("Unexpected error summarizing %s", github_url)
        return _error(f"Unexpected error: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR)

    logger.info("Successfully summarized %s", github_url)
    return result
