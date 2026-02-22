import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.app.schemas import ErrorResponse, SummarizeRequest, SummarizeResponse
from src.app.services.github_fetcher import fetch_repo_context
from src.app.services.summarizer import run_summarize_chain

router = APIRouter()
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


def _github_rate_limit_message(response: httpx.Response) -> str:
    reset_raw = response.headers.get("x-ratelimit-reset")
    if reset_raw and reset_raw.isdigit():
        reset_dt = datetime.fromtimestamp(int(reset_raw), tz=UTC)
        reset_text = reset_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            "GitHub API rate limit exceeded. "
            f"Rate limit resets at {reset_text}. "
            "Set GITHUB_TOKEN to increase limits."
        )
    return "GitHub API rate limit exceeded. Please try again later or set GITHUB_TOKEN."


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def summarize(request: Request) -> JSONResponse | SummarizeResponse:
    try:
        body = await request.json()
    except Exception:
        return _error("Request body must be valid JSON.", status.HTTP_400_BAD_REQUEST)

    try:
        payload = SummarizeRequest(**body)
    except ValidationError as exc:
        messages = "; ".join(err["msg"] for err in exc.errors())
        return _error(messages, status.HTTP_400_BAD_REQUEST)

    github_url = payload.github_url
    logger.info("Summarize request for: %s", github_url)

    try:
        context = await fetch_repo_context(github_url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return _error(
                f"Repository not found: '{github_url}'. Make sure it is public and the URL is correct.",
                status.HTTP_404_NOT_FOUND,
            )
        if exc.response.status_code in (403, 429):
            return _error(
                _github_rate_limit_message(exc.response),
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        logger.exception("GitHub API error for %s", github_url)
        return _error(f"GitHub API error: {exc.response.status_code}", status.HTTP_502_BAD_GATEWAY)
    except httpx.RequestError as exc:
        logger.exception("Network error fetching %s", github_url)
        return _error(f"Network error while contacting GitHub: {exc}", status.HTTP_502_BAD_GATEWAY)
    except ValueError as exc:
        return _error(str(exc), status.HTTP_400_BAD_REQUEST)

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
