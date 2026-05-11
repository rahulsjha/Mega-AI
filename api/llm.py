"""Shared LLM builders for agent orchestration."""

import os

from langchain_openai import ChatOpenAI


def build_openrouter_llm(max_completion_tokens: int):
    """Build an OpenRouter-backed ChatOpenAI client when configured."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None

    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        api_key=api_key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        max_completion_tokens=max_completion_tokens,
        temperature=0,
    )
