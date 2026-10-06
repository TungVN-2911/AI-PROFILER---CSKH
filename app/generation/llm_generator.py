"""Engagement generation with bounded LLM retries and a deterministic fallback.

Flow: LLM draft → guardrails → (violations as feedback, ≤ LLM_MAX_RETRIES retries) → deterministic draft →
guardrails. A draft is only returned when it has zero violations; otherwise the result carries no draft
and the pipeline reports PARTIAL_OR_PRIVATE. Raw LLM output is never trusted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from app.config import Settings
from app.generation.deterministic import generate_deterministic
from app.generation.prompts import SYSTEM_PROMPT, build_user_prompt
from app.guardrails import EngagementDraft, validate_draft
from app.intel import NEUTRAL_ADDRESSING, Addressing
from app.llm.base import LLMClient, LLMError
from app.models import FactLedger

log = logging.getLogger(__name__)

# Errors where an immediate retry of the same request cannot help.
NON_RETRYABLE = frozenset({"no_credentials", "auth", "refusal", "rate_limited", "unsupported_input"})


@dataclass
class GenerationResult:
    draft: EngagementDraft | None
    mode: Literal["llm", "deterministic", "none"]
    attempts: int = 0
    history: list[str] = field(default_factory=list)
    model_id: str | None = None
    error: str | None = None


def _llm_attempts(
    ledger: FactLedger, settings: Settings, llm: LLMClient, result: GenerationResult, addressing: Addressing
) -> EngagementDraft | None:
    feedback: list[str] | None = None
    for _ in range(1 + settings.llm_max_retries):
        result.attempts += 1
        n = result.attempts
        prompt = build_user_prompt(
            ledger, settings.default_message_count, settings.output_language, feedback, addressing
        )
        try:
            draft = llm.generate_structured(system=SYSTEM_PROMPT, user=prompt, output_model=EngagementDraft)
        except LLMError as exc:
            result.history.append(f"attempt {n}: LLM error ({exc.kind}) {exc.detail}".rstrip())
            log.warning("LLM attempt %d failed: %s", n, exc)
            if exc.kind in NON_RETRYABLE:
                break
            feedback = (
                ["the output did not match the required JSON schema"] if exc.kind == "invalid_output" else None
            )
            continue
        violations = validate_draft(draft, ledger)
        if not violations:
            return draft
        result.history.extend(f"attempt {n}: {v}" for v in violations)
        log.warning("LLM attempt %d rejected with %d violation(s)", n, len(violations))
        feedback = [str(v) for v in violations]
    return None


def generate_engagement(
    ledger: FactLedger,
    settings: Settings,
    llm: LLMClient | None,
    addressing: Addressing = NEUTRAL_ADDRESSING,
) -> GenerationResult:
    result = GenerationResult(draft=None, mode="none", model_id=llm.model_id if llm else None)

    if llm is not None:
        draft = _llm_attempts(ledger, settings, llm, result, addressing)
        result.model_id = llm.model_id  # the model that actually served (may be a fallback model)
        if draft is not None:
            result.draft, result.mode = draft, "llm"
            return result
        result.history.append("LLM drafts exhausted; falling back to the deterministic generator")

    try:
        draft = generate_deterministic(ledger, settings.default_message_count, addressing)
    except ValueError as exc:
        result.error = f"bộ sinh tin nhắn mẫu không tạo được bản nháp có căn cứ: {exc}"
        return result
    violations = validate_draft(draft, ledger)
    if violations:
        result.history.extend(f"deterministic: {v}" for v in violations)
        result.error = "bản nháp mẫu không qua được kiểm tra"
        return result
    result.draft, result.mode = draft, "deterministic"
    return result
