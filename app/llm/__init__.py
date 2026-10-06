"""LLM access behind the `LLMClient` protocol. Provider adapters (Claude, Gemini) are imported lazily so that the
deterministic mode never loads a provider SDK."""

from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.llm.base import LLMClient, LLMError

GenerationMode = Literal["auto", "llm", "deterministic"]


def get_llm_client(settings: Settings, mode: GenerationMode) -> LLMClient | None:
    """None means "use the deterministic generator"."""
    if mode == "deterministic":
        return None
    provider = settings.resolved_provider
    if provider is None:
        if mode == "llm":
            raise LLMError(
                "no_credentials",
                f"--mode llm cần đặt ANTHROPIC_API_KEY hoặc GEMINI_API_KEY (LLM_PROVIDER={settings.llm_provider})",
            )
        return None
    if provider == "gemini":
        from app.llm.gemini_client import GeminiLLMClient

        return GeminiLLMClient(settings)
    from app.llm.anthropic_client import AnthropicLLMClient

    return AnthropicLLMClient(settings)
