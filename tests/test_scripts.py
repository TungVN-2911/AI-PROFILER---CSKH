"""Tooling for consented real-profile runs. Subprocesses inherit PROFILER_NO_DOTENV (conftest)."""

import json
import os
import subprocess
import sys

from app.config import PROJECT_ROOT
from app.schema import parse_output
from app.sources.provided import load_raw_profile

NEW_PROFILE = PROJECT_ROOT / "scripts" / "new_profile.py"
RUN_PROFILES = PROJECT_ROOT / "scripts" / "run_test_profiles.py"
COMMITTED = [PROJECT_ROOT / "test_results.json", PROJECT_ROOT / "output.json", PROJECT_ROOT / "evidence.json"]


def run(script, *args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, env=env, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


def test_new_profile_writes_a_valid_template(tmp_path):
    out = tmp_path / "real" / "lan.json"
    code, stdout, _ = run(NEW_PROFILE, "--url", "https://m.facebook.com/Some.Real.User/?ref=share", "--out", str(out))
    assert code == 0
    raw = load_raw_profile(out)
    assert raw.facebook_url == "https://www.facebook.com/some.real.user"
    assert raw.synthetic is False and raw.collection_method == "manual_export"
    assert raw.display_name is None and raw.public_posts == []
    assert "đồng ý" in stdout and "--profile-file" in stdout


def test_new_profile_refuses_to_overwrite_and_rejects_bad_urls(tmp_path):
    out = tmp_path / "p.json"
    assert run(NEW_PROFILE, "--url", "https://www.facebook.com/a.b.c", "--out", str(out))[0] == 0
    out.write_text(out.read_text(encoding="utf-8").replace('"display_name": ""', '"display_name": "Đã điền"'), encoding="utf-8")
    code, _, err = run(NEW_PROFILE, "--url", "https://www.facebook.com/a.b.c", "--out", str(out))
    assert code == 1 and "không ghi đè" in err
    assert load_raw_profile(out).display_name == "Đã điền"
    assert run(NEW_PROFILE, "--url", "https://www.facebook.com/a.b.c", "--out", str(out), "--force")[0] == 0
    code, _, err = run(NEW_PROFILE, "--url", "https://www.facebook.com/groups/1", "--out", str(tmp_path / "x.json"))
    assert code == 2 and err.startswith("INVALID_INPUT:")


def test_batch_run_over_a_profiles_dir_never_touches_committed_artifacts(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    # A filled-in profile (copied from a fixture, marked as real data) and an unfilled template.
    filled = json.loads((PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json").read_text(encoding="utf-8"))
    filled.update(facebook_url="https://www.facebook.com/consented.user", synthetic=False, collection_method="manual_export")
    (profiles / "consented.json").write_text(json.dumps(filled, ensure_ascii=False), encoding="utf-8")
    assert run(NEW_PROFILE, "--url", "https://www.facebook.com/empty.template", "--out", str(profiles / "empty.json"))[0] == 0
    (profiles / "broken.json").write_text("{", encoding="utf-8")
    before = {p: p.stat().st_mtime_ns for p in COMMITTED}

    results_file = tmp_path / "results.json"
    code, _, _ = run(RUN_PROFILES, "--profiles-dir", str(profiles), "--results", str(results_file), "--runs-dir", str(tmp_path / "runs"))

    report = json.loads(results_file.read_text(encoding="utf-8"))
    by_case = {r["case"]: r for r in report["results"]}
    assert set(by_case) == {"broken", "consented", "empty"}
    assert by_case["consented"]["result"] == "PASS" and by_case["consented"]["status"] == "SUCCESS"
    assert by_case["empty"]["result"] == "PASS" and by_case["empty"]["error_note"].startswith("INSUFFICIENT_DATA:")
    assert by_case["broken"]["result"] == "FAIL" and "không phải JSON hợp lệ" in by_case["broken"]["reason"]
    assert code == 1  # a failing case makes the run fail
    for entry in (by_case["consented"], by_case["empty"]):
        parse_output(entry["output"])
    assert "đồng ý" in report["data_note"]
    assert {p: p.stat().st_mtime_ns for p in COMMITTED} == before

    first_run_dirs = set((tmp_path / "runs").iterdir())
    run(RUN_PROFILES, "--profiles-dir", str(profiles), "--results", str(results_file), "--runs-dir", str(tmp_path / "runs"))
    second_run_dirs = set((tmp_path / "runs").iterdir())
    assert len(first_run_dirs) == 1
    assert len(second_run_dirs) == 2 and first_run_dirs < second_run_dirs


def test_missing_profiles_dir_is_an_error(tmp_path):
    code, _, err = run(RUN_PROFILES, "--profiles-dir", str(tmp_path / "nope"), "--results", str(tmp_path / "r.json"))
    assert code == 2 and "Không tìm thấy thư mục" in err
