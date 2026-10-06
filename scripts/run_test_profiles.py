"""Final test run: run representative profiles through the real CLI and record results.

Usage:  python scripts/run_test_profiles.py
Writes: test_results.json, and output.json / evidence.json from the public-rich run (repo root).
Per-case files go to runs/test_run/<case>/ (git-ignored).

Real profiles with consent:
        python scripts/run_test_profiles.py --profiles-dir runs/real [--results FILE] [--runs-dir DIR]
Runs every *.json profile file in the folder (see scripts/new_profile.py) and creates a timestamped,
per-run folder under runs/real_run/. An explicitly supplied --results path is updated on each run.
Committed artifacts (test_results.json, output.json, evidence.json) are never touched in this mode.
"""

from __future__ import annotations

import argparse
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
from app.sources.base import SourceError  # noqa: E402
from app.sources.provided import load_raw_profile  # noqa: E402

RUN_DIR = ROOT / "runs" / "test_run"

DATA_NOTE = (
    "TECHNICAL LIMITATION: các trường hợp profile dùng persona thử nghiệm giả lập (fixtures/profiles, 'synthetic': true), "
    "không phải dữ liệu Facebook thật. Facebook yêu cầu đăng nhập để xem gần như toàn bộ nội dung trang cá nhân và agent "
    "không đăng nhập hay vượt qua cơ chế kiểm soát truy cập; trường hợp 'live_facebook_attempt' ghi lại kết quả thực tế "
    "của một request không đăng nhập. Để chạy trên profile thật (có sự đồng ý), xem README mục 5 'Chạy với trang cá nhân thật (có sự đồng ý)'."
)

CASES = [
    {"case": "public_rich", "purpose": "Rich public profile → full SUCCESS output",
     "args": ["--url", "https://www.facebook.com/fixture.minh.anh"]},
    {"case": "partial_access", "purpose": "PARTIAL access, name + 2 facts → shorter grounded sequence",
     "args": ["--url", "https://www.facebook.com/fixture.thu.ha"]},
    {"case": "public_no_image", "purpose": "No public image → PARTIAL_OR_PRIVATE / NO_IMAGE (brief §4)",
     "args": ["--url", "https://www.facebook.com/fixture.quoc.bao"]},
    {"case": "self_declared_female", "purpose": "Self-declared gender/birth year → labelled demographics, 'chị/em' address",
     "args": ["--url", "https://www.facebook.com/fixture.khanh.linh"]},
    {"case": "private_profile", "purpose": "Private profile → honest PARTIAL_OR_PRIVATE",
     "args": ["--url", "https://www.facebook.com/fixture.private.user"]},
    {"case": "dead_link", "purpose": "Dead link → NOT_FOUND",
     "args": ["--url", "https://www.facebook.com/fixture.dead.link"]},
    {"case": "llm_mode_public_rich", "purpose": "LLM generation on the rich profile (Gemini or Claude; requires an API key)",
     "args": ["--url", "https://www.facebook.com/fixture.minh.anh", "--mode", "llm"], "needs_llm": True},
    {"case": "live_facebook_attempt",
     "purpose": "One unauthenticated public-meta request to facebook.com (Meta's own page, not a private person)",
     "args": ["--url", "https://www.facebook.com/facebook", "--live"]},
]


def run_case(case: dict, llm_available: bool, run_dir: Path = RUN_DIR) -> dict:
    entry = {"case": case["case"], "purpose": case["purpose"], "command": "python main.py " + " ".join(
        f'"{a}"' if a.startswith("http") else a for a in case["args"])}
    if case.get("needs_llm") and not llm_available:
        entry.update(result="NOT_RUN", reason="Môi trường chưa cấu hình ANTHROPIC_API_KEY hoặc GEMINI_API_KEY; "
                     "nhánh LLM mới chỉ được kiểm chứng bằng client giả lập trong bộ test.")
        return entry

    out_dir = run_dir / case["case"]
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


REAL_NOTE = (
    "Dữ liệu trang cá nhân thật được nhập thủ công với sự đồng ý của chủ trang (collection_method=manual_export). "
    "File này nằm trong runs/ (git-ignore); chỉ công bố khi chủ trang đồng ý."
)


def _report(results: list[dict], settings, note: str) -> dict:
    return {
        "project": "Facebook Profiler Agent (TES-3808)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "llm_available": settings.has_llm_credentials,
            "llm_provider": settings.resolved_provider,
            "llm_model": settings.active_model,
        },
        "data_note": note,
        "summary": {
            "cases": len(results),
            "pass": sum(r["result"] == "PASS" for r in results),
            "fail": sum(r["result"] == "FAIL" for r in results),
            "not_run": sum(r["result"] == "NOT_RUN" for r in results),
        },
        "results": results,
    }


def real_profile_results(profiles_dir: Path, llm_available: bool, run_dir: Path) -> list[dict]:
    results = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            url = load_raw_profile(path).facebook_url
        except SourceError as exc:
            results.append({"case": path.stem, "result": "FAIL", "reason": str(exc)})
            continue
        case = {"case": path.stem, "purpose": f"Trang cá nhân thật (dữ liệu có đồng ý): {path.name}",
                "args": ["--url", url, "--profile-file", str(path)]}
        results.append(run_case(case, llm_available, run_dir))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run test profiles through the CLI and record the results.")
    parser.add_argument("--profiles-dir", type=Path, help="folder of consented real profile files (*.json)")
    parser.add_argument("--results", type=Path,
                        help="results file for --profiles-dir (default: per-run timestamped file)")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs" / "real_run",
                        help="base folder for per-run, per-profile outputs (default: runs/real_run)")
    args = parser.parse_args(argv)

    settings = load_settings()
    llm_available = settings.has_llm_credentials

    if args.profiles_dir is not None:
        if not args.profiles_dir.is_dir():
            print(f"Không tìm thấy thư mục: {args.profiles_dir}", file=sys.stderr)
            return 2
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_dir = args.runs_dir / run_id
        results_path = args.results or run_dir / "test_results_real.json"
        results = real_profile_results(args.profiles_dir, llm_available, run_dir)
        report = _report(results, settings, REAL_NOTE)
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Lưu lượt chạy tại: {run_dir}", file=sys.stderr)
        print(f"Báo cáo: {results_path}", file=sys.stderr)
    else:
        results = [run_case(case, llm_available) for case in CASES]
        public = RUN_DIR / "public_rich"
        if (public / "output.json").exists():
            shutil.copyfile(public / "output.json", ROOT / "output.json")
            shutil.copyfile(public / "evidence.json", ROOT / "evidence.json")
        report = _report(results, settings, DATA_NOTE)
        (ROOT / "test_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for r in results:
        print(f"{r['case']:<24} {r['result']:<8} {r.get('status') or r.get('reason', '')}", file=sys.stderr)
    return 0 if report["summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
