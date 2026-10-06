"""Pipeline orchestration and the status / error matrix (architecture.md §2, §6; FR-004, FR-009, FR-014).

Every path returns a strict-schema output, an evidence report and an exit code:
    0 = SUCCESS or an honest PARTIAL_OR_PRIVATE, 2 = invalid input / configuration, 1 = internal error.
`ZERO_SALES_CONFIRMED` is only written after the final draft passes the guardrails in this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.generation.llm_generator import GenerationResult, generate_engagement
from app.guardrails import validate_draft
from app.input import InputError, validate_profile_url
from app.intel import build_intelligence
from app.ledger import build_ledger, evaluate_sufficiency
from app.llm import GenerationMode, get_llm_client
from app.llm.base import LLMClient, LLMError
from app.models import READABLE_STATES, AccessState, FactLedger
from app.schema import (
    TRIGGER_TIME,
    ZERO_SALES_CONFIRMED,
    EstimatedDemographics,
    EthicalRapport,
    EveningCadence,
    EvidenceReport,
    Grounding,
    MessageGrounding,
    PartialOutput,
    ProfileData,
    SuccessOutput,
    ValidationSummary,
)
from app.sources.base import SYNTHETIC_NOTE, ProfileSource, SourceError, acquire_from_chain
from app.sources.live_meta import SCOPE_NOTE, LivePublicMetaSource
from app.sources.provided import FixtureStoreSource, ProvidedFileSource
from app.vision import extract_visual_context

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_INPUT = 2

# Informational limitation texts that do not explain a failure.
_CONTEXT_NOTES = frozenset({SYNTHETIC_NOTE, SCOPE_NOTE})


@dataclass(frozen=True)
class PipelineOptions:
    profile_file: Path | None = None
    mode: GenerationMode = "auto"
    live: bool | None = None  # None → settings.live_fetch_enabled
    reference_year: int | None = None


@dataclass(frozen=True)
class PipelineResult:
    output: SuccessOutput | PartialOutput
    evidence: EvidenceReport
    exit_code: int


def _partial(url: str, note: str, exit_code: int, **evidence: object) -> PipelineResult:
    return PipelineResult(
        output=PartialOutput(status="PARTIAL_OR_PRIVATE", facebook_url=url, error_note=note),
        evidence=EvidenceReport(facebook_url=url, output_status="PARTIAL_OR_PRIVATE", **evidence),
        exit_code=exit_code,
    )


def run_pipeline(
    raw_url: str | None,
    options: PipelineOptions,
    settings: Settings,
    llm_client: LLMClient | None = None,
    http_transport: httpx.BaseTransport | None = None,
) -> PipelineResult:
    try:
        return _run(raw_url, options, settings, llm_client, http_transport)
    except Exception as exc:  # INTERNAL_ERROR catch-all: never crash, never invent
        log.exception("unexpected pipeline error")
        note = f"INTERNAL_ERROR: unexpected {type(exc).__name__}; no profile output was produced and nothing was invented."
        return _partial(raw_url or "", note, EXIT_INTERNAL, technical_limitations=[note])


def _run(
    raw_url: str | None,
    options: PipelineOptions,
    settings: Settings,
    llm_client: LLMClient | None,
    http_transport: httpx.BaseTransport | None,
) -> PipelineResult:
    # 1. Input validation
    try:
        url = validate_profile_url(raw_url)
    except InputError as exc:
        return _partial(exc.raw, exc.error_note, EXIT_INPUT, access_state=AccessState.INVALID_INPUT,
                        technical_limitations=[exc.error_note])
    log.info("canonical URL: %s", url.url)

    # 2. LLM availability (fail fast in --mode llm without credentials)
    llm: LLMClient | None = None
    if options.mode != "deterministic":
        try:
            llm = llm_client or get_llm_client(settings, options.mode)
        except LLMError as exc:
            note = f"TECHNICAL LIMITATION: {exc.detail or exc.kind}."
            return _partial(url.url, note, EXIT_INPUT, technical_limitations=[note])

    # 3. Data acquisition
    store = FixtureStoreSource(settings.profile_store_dir)
    sources: list[ProfileSource] = []
    if options.profile_file is not None:
        sources.append(ProvidedFileSource(options.profile_file))
    live = settings.live_fetch_enabled if options.live is None else options.live
    sources += [store, LivePublicMetaSource(enabled=live, timeout_seconds=15.0, transport=http_transport)]
    try:
        acq = acquire_from_chain(sources, url)
    except SourceError as exc:
        note = f"INVALID_INPUT: {exc}"
        return _partial(url.url, note, EXIT_INPUT, access_state=AccessState.INVALID_INPUT, technical_limitations=[note])
    limitations = [*acq.limitations, *(f"profile store: {e}" for e in store.load_errors)]
    log.info("acquired via %s: %s", acq.source_name, acq.access_state.value)

    # 4. Normalization + visual context (readable profiles only)
    ledger = build_ledger(acq.raw)
    visual_context = "NOT_AVAILABLE: profile content is not accessible"
    if acq.access_state in READABLE_STATES:
        vision = extract_visual_context(acq.raw, ledger, llm, transport=http_transport)
        ledger, visual_context = vision.ledger, vision.visual_context
        limitations += vision.notes

    common = dict(
        access_state=acq.access_state,
        sources_used=[acq.source_name],
        synthetic_data=acq.synthetic,
        collected_at=acq.raw.collected_at.isoformat() if acq.raw and acq.raw.collected_at else None,
        fact_ledger=ledger.facts,
        unknown_fields=ledger.unknown_fields,
    )

    # 5. Sufficiency gate
    gate = evaluate_sufficiency(acq.access_state, ledger, settings)
    if not gate.ok:
        details = [n for n in acq.limitations if n not in _CONTEXT_NOTES and n != gate.note]
        note = " | ".join([gate.note, *details])
        return _partial(url.url, note, EXIT_OK, technical_limitations=limitations, **common)

    # 6. Intelligence + generation
    intel = build_intelligence(ledger, options.reference_year)
    gen = generate_engagement(ledger, settings, llm)
    if gen.draft is None:
        note = (
            "INSUFFICIENT_DATA: grounded rapport messages could not be produced without inventing content"
            f" ({gen.error})."
        )
        return _partial(url.url, note, EXIT_OK, technical_limitations=limitations,
                        generation_mode="none", model_id=gen.model_id,
                        validation=ValidationSummary(passed=False, attempts=gen.attempts, violations=gen.history),
                        **common)

    # 7. Final guardrail check — the only place ZERO_SALES_CONFIRMED can come from.
    violations = validate_draft(gen.draft, ledger)
    if violations:
        raise RuntimeError(f"generated draft failed final validation: {violations[0]}")

    return _success(url.url, ledger, intel, gen, visual_context, limitations, common)


def _success(url, ledger: FactLedger, intel, gen: GenerationResult, visual_context, limitations, common) -> PipelineResult:
    draft = gen.draft
    if gen.mode == "llm" and draft.apparent_lifestyle is not None:
        lifestyle, lifestyle_ids = draft.apparent_lifestyle.text, draft.apparent_lifestyle.fact_ids
    else:
        lifestyle, lifestyle_ids = intel.apparent_lifestyle, intel.lifestyle_fact_ids

    output = SuccessOutput(
        status="SUCCESS",
        facebook_url=url,
        profile_data=ProfileData(
            customer_name=intel.customer_name,
            visual_context=visual_context,
            estimated_demographics=EstimatedDemographics(
                gender=intel.gender,
                estimated_age_range=intel.estimated_age_range,
                apparent_lifestyle=lifestyle,
            ),
        ),
        ethical_rapport=EthicalRapport(
            core_empathy_angle=draft.core_empathy_angle.text,
            dialogue_sequence_10=[m.text for m in draft.messages],
            sales_mention_check=ZERO_SALES_CONFIRMED,
        ),
        evening_cadence_20pm=EveningCadence(trigger_time=TRIGGER_TIME, evening_hook_message=draft.evening_hook.text),
    )
    evidence = EvidenceReport(
        facebook_url=url,
        output_status="SUCCESS",
        generation_mode=gen.mode,
        model_id=gen.model_id,
        grounding=Grounding(
            core_empathy_angle=draft.core_empathy_angle.fact_ids,
            apparent_lifestyle=lifestyle_ids,
            messages=[MessageGrounding(index=i, kind=m.kind, fact_ids=m.fact_ids) for i, m in enumerate(draft.messages)],
            evening_hook=draft.evening_hook.fact_ids,
        ),
        validation=ValidationSummary(
            passed=True,
            attempts=gen.attempts + (1 if gen.mode == "deterministic" else 0),
            violations=gen.history,
        ),
        technical_limitations=limitations,
        **common,
    )
    return PipelineResult(output=output, evidence=evidence, exit_code=EXIT_OK)
