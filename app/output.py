"""Serialization and file output. stdout and output.json always carry the identical document."""

from __future__ import annotations

import json
from pathlib import Path

from app.schema import EvidenceReport, PartialOutput, SuccessOutput, to_json_dict


def serialize_output(output: SuccessOutput | PartialOutput) -> str:
    return json.dumps(to_json_dict(output), ensure_ascii=False, indent=2)


def serialize_evidence(evidence: EvidenceReport) -> str:
    return json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
