"""Final test run (FR-016, brief §25): run representative profiles through the real CLI and record results.

Usage:  python scripts/run_test_profiles.py
Writes: test_results.json, and output.json / evidence.json from the public-rich run (repo root).
Per-case files go to runs/test_run/<case>/ (git-ignored).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.schema import SuccessOutput, parse_output  # noqa: E402

RUN_DIR = ROOT / "runs" / "test_run"

DATA_NOTE = (
    "TECHNICAL LIMITATION: profile cases use synthetic fixture personas (fixtures/profiles, 'synthetic': true), "
    "not real Facebook data. Facebook requires login for nearly all profile content and this agent does not log in "
    "or bypass access controls; the 'live_facebook_attempt' case documents what one unauthenticated request "
    "actually returns."
)

CASES = [
    {"case": "public_rich", "purpose": "Rich public profile → full SUCCESS output",
     "args": ["--url", "https://www.facebook.com/fixture.minh.anh"]},
    {"case": "partial_access", "purpose": "PARTIAL access, name + 2 facts → shorter grounded sequence",
     "args": ["--url", "https://www.facebook.com/fixture.thu.ha"]},
    {"case": "public_no_image", "purpose": "No public image → visual_context NOT_AVAILABLE",
     "args": ["--url", "https://www.facebook.com/fixture.quoc.bao"]},
    {"case": "private_profile", "purpose": "Private profile → honest PARTIAL_OR_PRIVATE",
     "args": ["--url", "https://www.facebook.com/fixture.private.user"]},
    {"case": "dead_link", "purpose": "Dead link → NOT_FOUND",
     "args": ["--url", "https://www.facebook.com/fixture.dead.link"]},
    {"case": "llm_mode_public_rich", "purpose": "Claude generation on the rich profile (requires ANTHROPIC_API_KEY)",
     "args": ["--url", "https://www.facebook.com/fixture.minh.anh", "--mode", "llm"], "needs_llm": True},
    {"case": "live_facebook_attempt",
     "purpose": "One unauthenticated public-meta request to facebook.com (Meta's own page, not a private person)",
     "args": ["--url", "https://www.facebook.com/facebook", "--live"]},
]


def run_case(case: dict, llm_available: bool) -> dict:
    entry = {"case": case["case"], "purpose": case["purpose"], "command": "python main.py " + " ".join(
        f'"{a}"' if a.startswith("http") else a for a in case["args"])}
    if case.get("needs_llm") and not llm_available:
        entry.update(result="NOT_RUN", reason="ANTHROPIC_API_KEY is not configured in this environment; "
                     "LLM path verified only with a scripted fake client in the test suite.")
        return entry

    out_dir = RUN_DIR / case["case"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file, ev_file = out_dir / "output.json", out_dir / "evidence.json"
    env = {**os.environ, "PYTHONIOENCODING": ""}
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *case["args"], "--output", str(out_file), "--evidence", str(ev_file)],
        cwd=ROOT, env=env, capture_output=True, timeout=300,
    )
    duration = round(time.perf_counter() - start, 2)
    stdout = proc.stdout.decode("utf-8")

    checks: dict[str, bool] = {}
    try:
        doc = json.loads(stdout)
        checks["stdout_is_single_json_document"] = True
    except json.JSONDecodeError:
        entry.update(result="FAIL", reason="stdout is not valid JSON", exit_code=proc.returncode)
        return entry
    checks["stdout_equals_output_json"] = doc == json.loads(out_file.read_text(encoding="utf-8"))
    try:
        parsed = parse_output(doc)
        checks["schema_valid"] = True
    except Exception:  # noqa: BLE001 - record any schema failure as a failed check
        parsed, checks["schema_valid"] = None, False
    evidence = json.loads(ev_file.read_text(encoding="utf-8"))
    if isinstance(parsed, SuccessOutput):
        checks["zero_sales_confirmed"] = parsed.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"
        checks["message_count_5_to_10"] = 5 <= len(parsed.ethical_rapport.dialogue_sequence_10) <= 10
        checks["every_message_grounding_recorded"] = len(evidence["grounding"]["messages"]) == len(
            parsed.ethical_rapport.dialogue_sequence_10)

    entry.update(
        result="PASS" if all(checks.values()) else "FAIL",
        exit_code=proc.returncode,
        duration_seconds=duration,
        status=doc.get("status"),
        error_note=doc.get("error_note"),
        access_state=evidence.get("access_state"),
        source=evidence.get("sources_used"),
        synthetic_data=evidence.get("synthetic_data"),
        generation_mode=evidence.get("generation_mode"),
        message_count=len(doc["ethical_rapport"]["dialogue_sequence_10"]) if doc.get("status") == "SUCCESS" else None,
        checks=checks,
        technical_limitations=evidence.get("technical_limitations", []),
        output=doc,
    )
    return entry


def main() -> int:
    settings = load_settings()
    llm_available = settings.has_llm_credentials
    results = [run_case(case, llm_available) for case in CASES]

    public = RUN_DIR / "public_rich"
    if (public / "output.json").exists():
        shutil.copyfile(public / "output.json", ROOT / "output.json")
        shutil.copyfile(public / "evidence.json", ROOT / "evidence.json")

    report = {
        "project": "Facebook Profiler Agent (TES-3808)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "llm_available": llm_available,
            "llm_model": settings.llm_model if llm_available else None,
        },
        "data_note": DATA_NOTE,
        "summary": {
            "cases": len(results),
            "pass": sum(r["result"] == "PASS" for r in results),
            "fail": sum(r["result"] == "FAIL" for r in results),
            "not_run": sum(r["result"] == "NOT_RUN" for r in results),
        },
        "results": results,
    }
    (ROOT / "test_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print(f"{r['case']:<24} {r['result']:<8} {r.get('status') or r.get('reason', '')}", file=sys.stderr)
    return 0 if report["summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
