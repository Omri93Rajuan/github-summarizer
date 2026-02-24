from src.app.services import github_fetcher, summarizer


def test_parse_response_with_wrapped_text():
    raw = """
    Here is the result:
    {
      "summary": "Project summary.",
      "technologies": ["Python", "FastAPI"],
      "structure": "Standard src layout."
    }
    Thanks.
    """

    result = summarizer._parse_response(raw)

    assert result.summary == "Project summary."
    assert result.technologies == ["Python", "FastAPI"]
    assert result.structure == "Standard src layout."


def test_binary_detection():
    assert github_fetcher._is_probably_binary(b"hello world\nprint('ok')\n") is False
    assert github_fetcher._is_probably_binary(b"\x00\x01\x02\x03binary") is True


def test_repo_context_respects_token_budget(monkeypatch):
    monkeypatch.setattr(github_fetcher, "MAX_CONTEXT_CHARS", 100_000)
    monkeypatch.setattr(github_fetcher, "MAX_CONTEXT_TOKENS", 20)
    monkeypatch.setattr(github_fetcher, "MAX_FILE_TOKENS", 20)

    ctx = github_fetcher.RepoContext(owner="o", repo="r")
    added = ctx.add("README.md", "x" * 500)

    assert added is True
    assert ctx.total_tokens <= github_fetcher.MAX_CONTEXT_TOKENS

