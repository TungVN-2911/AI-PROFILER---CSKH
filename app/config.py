"""Runtime configuration loaded from environment variables and an optional `.env` file.

Precedence (highest first): explicit overrides > process environment > `.env` > defaults.
Empty values (e.g. `ANTHROPIC_API_KEY=` copied from `.env.example`) are treated as unset.
This module must not import any LLM provider SDK.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Settings field name -> environment variable name.
ENV_VARS: dict[str, str] = {
    "llm_provider": "LLM_PROVIDER",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "llm_model": "LLM_MODEL",
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
    "gemini_fallback_models": "GEMINI_FALLBACK_MODELS",
    "llm_timeout_seconds": "LLM_TIMEOUT_SECONDS",
    "llm_max_retries": "LLM_MAX_RETRIES",
    "output_language": "OUTPUT_LANGUAGE",
    "live_fetch_enabled": "LIVE_FETCH_ENABLED",
    "profile_store_dir": "PROFILE_STORE_DIR",
    "min_grounding_facts": "MIN_GROUNDING_FACTS",
    "default_message_count": "DEFAULT_MESSAGE_COUNT",
}


class ConfigError(ValueError):
    """Raised when configuration values are invalid."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # CR-004: "auto" prefers Claude when both keys exist, else whichever key is configured.
    llm_provider: Literal["auto", "anthropic", "gemini"] = "auto"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = Field(default="claude-opus-5-5", min_length=1)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1)
    # BUG-002: tried in order when the primary model is overloaded, out of quota or unavailable.
    gemini_fallback_models: str = "gemini-3.5-flash,gemini-3.5-flash-lite"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    output_language: str = Field(default="vi", pattern=r"^[a-z]{2}$")
    live_fetch_enabled: bool = False
    profile_store_dir: Path = Field(default=Path("fixtures/profiles"), validate_default=True)
    min_grounding_facts: int = Field(default=2, ge=1)
    default_message_count: int = Field(default=10, ge=5, le=10)

    @field_validator("profile_store_dir")
    @classmethod
    def _resolve_store_dir(cls, value: Path) -> Path:
        # Relative paths are anchored at the project root so the CLI works from any cwd.
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def has_anthropic_credentials(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())

    @property
    def has_gemini_credentials(self) -> bool:
        return self.gemini_api_key is not None and bool(self.gemini_api_key.get_secret_value())

    @property
    def resolved_provider(self) -> Literal["anthropic", "gemini"] | None:
        """The LLM provider to use, or None when its key is missing (→ deterministic mode)."""
        if self.llm_provider == "anthropic":
            return "anthropic" if self.has_anthropic_credentials else None
        if self.llm_provider == "gemini":
            return "gemini" if self.has_gemini_credentials else None
        if self.has_anthropic_credentials:
            return "anthropic"
        return "gemini" if self.has_gemini_credentials else None

    @property
    def gemini_model_chain(self) -> list[str]:
        chain = [self.gemini_model, *(m.strip() for m in self.gemini_fallback_models.split(","))]
        return list(dict.fromkeys(m for m in chain if m))

    @property
    def has_llm_credentials(self) -> bool:
        return self.resolved_provider is not None

    @property
    def active_model(self) -> str | None:
        provider = self.resolved_provider
        if provider is None:
            return None
        return self.llm_model if provider == "anthropic" else self.gemini_model


def load_settings(
    overrides: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = PROJECT_ROOT / ".env",
) -> Settings:
    """Build Settings from defaults, `.env`, the environment and explicit overrides.

    `env` defaults to `os.environ`; pass `dotenv_path=None` to skip reading `.env`.
    """
    sources: list[Mapping[str, str | None]] = []
    # PROFILER_NO_DOTENV=1 ignores .env (used by the test suite so a real API key never leaks into tests).
    skip_dotenv = os.environ.get("PROFILER_NO_DOTENV", "").strip().lower() in {"1", "true", "yes"}
    if dotenv_path is not None and not skip_dotenv and dotenv_path.is_file():
        sources.append(dotenv_values(dotenv_path))
    sources.append(os.environ if env is None else env)

    values: dict[str, Any] = {}
    for source in sources:
        for field_name, var_name in ENV_VARS.items():
            raw = source.get(var_name)
            if raw is not None and raw.strip() != "":
                values[field_name] = raw.strip()
    if overrides:
        values.update({k: v for k, v in overrides.items() if v is not None})

    try:
        return Settings(**values)
    except ValidationError as exc:
        problems = "; ".join(
            f"{ENV_VARS.get(str(err['loc'][0]), err['loc'][0])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"Cấu hình không hợp lệ: {problems}") from None
