"""Command-line interface (FR-001, FR-013, NFR-001, NFR-008, NFR-010).

stdout receives exactly one JSON document — also for usage and configuration errors — and the same document
is written to --output. Logs go to stderr only. Exit codes: 0 ok, 2 invalid input/configuration, 1 internal.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.config import ConfigError, load_settings
from app.output import serialize_evidence, serialize_output, write_text
from app.pipeline import EXIT_INPUT, EXIT_INTERNAL, PipelineOptions, PipelineResult, run_pipeline
from app.schema import EvidenceReport, PartialOutput

log = logging.getLogger("app.cli")


class _UsageError(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise _UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="python main.py",
        description="Facebook Profiler Agent (TES-3808): fact-grounded profile, zero-sales rapport messages and a 20:00 hook.",
    )
    parser.add_argument("--url", help="Facebook profile URL, e.g. https://www.facebook.com/<username>")
    parser.add_argument("--profile-file", type=Path, help="JSON file with legitimately provided profile data")
    parser.add_argument("--output", type=Path, default=Path("output.json"), help="output file (default: output.json)")
    parser.add_argument("--evidence", type=Path, default=Path("evidence.json"), help="evidence file (default: evidence.json)")
    parser.add_argument("--mode", choices=["auto", "llm", "deterministic"], default="auto",
                        help="auto: Claude if ANTHROPIC_API_KEY is set, else templates (default)")
    parser.add_argument("--live", action="store_true", default=None,
                        help="opt-in: one unauthenticated request for public meta tags (never logs in)")
    parser.add_argument("--messages", type=int, help="target number of rapport messages (5-10, default 10)")
    parser.add_argument("--verbose", action="store_true", help="log pipeline stages to stderr")
    return parser


def _configure_streams(verbose: bool) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _error_result(url: str, note: str, exit_code: int) -> PipelineResult:
    return PipelineResult(
        output=PartialOutput(status="PARTIAL_OR_PRIVATE", facebook_url=url, error_note=note),
        evidence=EvidenceReport(facebook_url=url, output_status="PARTIAL_OR_PRIVATE", technical_limitations=[note]),
        exit_code=exit_code,
    )


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    output_path, evidence_path = Path("output.json"), Path("evidence.json")
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        _configure_streams(verbose=False)
        result = _error_result("", f"INVALID_INPUT: tham số dòng lệnh không hợp lệ ({exc})", EXIT_INPUT)
    else:
        _configure_streams(args.verbose)
        output_path, evidence_path = args.output, args.evidence
        try:
            overrides = {"default_message_count": args.messages} if args.messages is not None else None
            settings = load_settings(overrides)
        except ConfigError as exc:
            result = _error_result(args.url or "", f"INVALID_INPUT: {exc}", EXIT_INPUT)
        else:
            options = PipelineOptions(profile_file=args.profile_file, mode=args.mode, live=args.live)
            result = run_pipeline(args.url, options, settings)

    document = serialize_output(result.output)
    exit_code = result.exit_code
    try:
        write_text(output_path, document)
        write_text(evidence_path, serialize_evidence(result.evidence))
    except OSError as exc:
        log.error("could not write output files: %s", exc)
        exit_code = EXIT_INTERNAL
    sys.stdout.write(document + "\n")
    sys.stdout.flush()
    return exit_code
