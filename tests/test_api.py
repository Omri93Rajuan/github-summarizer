from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.schemas.response import SummarizeResponse
from src.app.api import routes


client = TestClient(app)


def test_summarize_success(monkeypatch):
    fake_context = "repo context"
    fake_result = SummarizeResponse(
        summary="A test summary",
        technologies=["Python", "FastAPI"],
        structure="Simple structure",
    )

    monkeypatch.setattr(routes, "fetch_repo_context", AsyncMock(return_value=fake_context))
    monkeypatch.setattr(routes, "run_summarize_chain", AsyncMock(return_value=fake_result))

    response = client.post(
        "/summarize",
        json={"github_url": "https://github.com/psf/requests"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "A test summary"
    assert data["technologies"] == ["Python", "FastAPI"]
    assert data["structure"] == "Simple structure"


def test_invalid_github_url_returns_400():
    response = client.post(
        "/summarize",
        json={"github_url": "https://gitlab.com/group/repo"},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert "https://github.com/" in data["message"]


def test_github_url_is_normalized(monkeypatch):
    fake_context = "repo context"
    fake_result = SummarizeResponse(
        summary="A test summary",
        technologies=["Python", "FastAPI"],
        structure="Simple structure",
    )
    fetch_mock = AsyncMock(return_value=fake_context)

    monkeypatch.setattr(routes, "fetch_repo_context", fetch_mock)
    monkeypatch.setattr(routes, "run_summarize_chain", AsyncMock(return_value=fake_result))

    response = client.post(
        "/summarize",
        json={"github_url": "https://github.com/psf/requests/issues"},
    )

    assert response.status_code == 200
    fetch_mock.assert_awaited_once_with("https://github.com/psf/requests")


def test_github_404_maps_to_404(monkeypatch):
    request = httpx.Request("GET", "https://api.github.com/repos/x/y")
    response_404 = httpx.Response(404, request=request)
    exc = httpx.HTTPStatusError("Not found", request=request, response=response_404)

    monkeypatch.setattr(routes, "fetch_repo_context", AsyncMock(side_effect=exc))

    response = client.post(
        "/summarize",
        json={"github_url": "https://github.com/owner/missing"},
    )

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    assert "Repository not found" in data["message"]


def test_github_rate_limit_maps_to_429(monkeypatch):
    request = httpx.Request("GET", "https://api.github.com/repos/x/y")
    response_403 = httpx.Response(
        403,
        request=request,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"},
    )
    exc = httpx.HTTPStatusError("Rate limited", request=request, response=response_403)

    monkeypatch.setattr(routes, "fetch_repo_context", AsyncMock(side_effect=exc))

    response = client.post(
        "/summarize",
        json={"github_url": "https://github.com/owner/repo"},
    )

    assert response.status_code == 429
    data = response.json()
    assert data["status"] == "error"
    assert "Rate limit resets at" in data["message"]
