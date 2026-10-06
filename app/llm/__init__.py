"""LLM access behind the `LLMClient` protocol. The Claude adapter is imported lazily so that the
deterministic mode never loads the provider SDK."""

from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.llm.base import LLMClient, LLMError

GenerationMode = Literal["auto", "llm", "deterministic"]


def get_llm_client(settings: Settings, mode: GenerationMode) -> LLMClient | None:
    """None means "use the deterministic generator"."""
    if mode == "deterministic":
        return None
    if not settings.has_llm_credentials:
        if mode == "llm":
            raise LLMError("no_credentials", "--mode llm requires ANTHROPIC_API_KEY to be set")
        return None
    from app.llm.anthropic_client import AnthropicLLMClient

    return AnthropicLLMClient(settings)
