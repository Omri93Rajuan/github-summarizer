"""
LangChain chain: structured prompt → Nebius LLM → parsed SummarizeResponse.
"""

import json
import logging
import os
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from src.models import SummarizeResponse

logger = logging.getLogger(__name__)

# ── prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior software engineer specializing in quickly understanding unfamiliar codebases.

Given repository content (directory tree, README, config files, source files), \
produce a concise structured analysis.

You MUST respond with a single valid JSON object — no markdown fences, no extra text:
{{
  "summary": "2-4 sentences: what the project does, who it is for, why it is useful",
  "technologies": ["main languages", "frameworks", "libraries", "databases", "tools"],
  "structure": "1-2 sentences describing the directory layout and key components"
}}
"""

HUMAN_PROMPT = """\
Repository: {github_url}

{context}
"""


# ── chain ─────────────────────────────────────────────────────────────────────

def _build_llm() -> ChatOpenAI:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise EnvironmentError("NEBIUS_API_KEY environment variable is not set.")

    return ChatOpenAI(
        model="openai/gpt-oss-120b",
        api_key=api_key,
        base_url="https://api.studio.nebius.ai/v1/",
        temperature=0.1,
        max_retries=2,
    )


def _parse_response(raw: str) -> SummarizeResponse:
    """Extract and validate JSON from the LLM response."""
    text = raw.strip()

    # Strip markdown code fences if the model added them despite instructions
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Last-resort: find the first JSON object in the response
        obj = re.search(r"\{.*\}", text, re.DOTALL)
        if not obj:
            raise ValueError(f"LLM returned non-JSON response: {text[:200]}")
        data = json.loads(obj.group())

    return SummarizeResponse(**data)


async def run_summarize_chain(github_url: str, context: str) -> SummarizeResponse:
    """Build and invoke the LangChain prompt → LLM chain."""
    llm = _build_llm()

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ])

    chain = prompt | llm

    logger.info("Sending context to LLM (%d chars)", len(context))
    response = await chain.ainvoke({"github_url": github_url, "context": context})

    raw: str = response.content  # type: ignore[assignment]
    logger.debug("Raw LLM response: %s", raw[:500])

    return _parse_response(raw)
