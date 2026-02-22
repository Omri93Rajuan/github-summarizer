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

