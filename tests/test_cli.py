import json
import os
import subprocess
import sys

import pytest

from app.config import PROJECT_ROOT
from app.schema import PartialOutput, SuccessOutput, parse_output

MAIN = PROJECT_ROOT / "main.py"
RICH_URL = "https://www.facebook.com/fixture.minh.anh"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "PYTHONIOENCODING", "PYTHONUTF8", "LLM_", "LIVE_", "PROFILE_STORE", "MIN_GROUNDING", "DEFAULT_MESSAGE", "OUTPUT_LANGUAGE"))}
    return env


def cli(tmp_path, *args):
    """Run main.py from a temp working directory; return (exit code, stdout text, stderr text)."""
    proc = subprocess.run(
        [sys.executable, str(MAIN), *args], cwd=tmp_path, env=clean_env(), capture_output=True, timeout=60
    )
    # Decode strictly as UTF-8: the CLI must not depend on the console code page.
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_rich_fixture_run_stdout_equals_output_json(tmp_path):
    code, out, err = cli(tmp_path, "--url", RICH_URL)
    assert code == 0, err
    doc = json.loads(out)  # stdout is exactly one JSON document
    assert doc == read(tmp_path / "output.json")
    assert isinstance(parse_output(doc), SuccessOutput)
    assert doc["profile_data"]["customer_name"] == "Nguyễn Minh Anh"  # Vietnamese intact
    assert "Nguyễn Minh Anh" in (tmp_path / "output.json").read_text(encoding="utf-8")  # not \\u-escaped
    evidence = read(tmp_path / "evidence.json")
    assert evidence["output_status"] == "SUCCESS" and evidence["generation_mode"] == "deterministic"
    assert err == ""  # no warnings without --verbose


def test_missing_url_emits_json_and_exit_2(tmp_path):
    code, out, _ = cli(tmp_path)
    assert code == 2
    doc = json.loads(out)
    assert isinstance(parse_output(doc), PartialOutput)
    assert doc["error_note"].startswith("INVALID_INPUT:")
    assert doc == read(tmp_path / "output.json")


def test_usage_error_emits_json_and_exit_2(tmp_path):
    code, out, _ = cli(tmp_path, "--url", RICH_URL, "--unknown-flag")
    assert code == 2
    doc = json.loads(out)
    assert doc["status"] == "PARTIAL_OR_PRIVATE" and doc["error_note"].startswith("INVALID_INPUT: unrecognized arguments")


def test_invalid_mode_choice_is_json(tmp_path):
    code, out, _ = cli(tmp_path, "--url", RICH_URL, "--mode", "magic")
    assert code == 2 and json.loads(out)["error_note"].startswith("INVALID_INPUT:")


def test_verbose_logs_go_to_stderr_only(tmp_path):
    code, out, err = cli(tmp_path, "--url", RICH_URL, "--verbose")
    assert code == 0
    json.loads(out)
    assert "canonical URL" in err and "acquired via profile_store" in err
    assert "canonical URL" not in out


@pytest.mark.parametrize("n", [5, 7])
def test_messages_flag(tmp_path, n):
    code, out, _ = cli(tmp_path, "--url", RICH_URL, "--messages", str(n))
    assert code == 0
    assert len(json.loads(out)["ethical_rapport"]["dialogue_sequence_10"]) == n


def test_messages_flag_out_of_range(tmp_path):
    code, out, _ = cli(tmp_path, "--url", RICH_URL, "--messages", "4")
    assert code == 2
    assert "DEFAULT_MESSAGE_COUNT" in json.loads(out)["error_note"]


def test_custom_output_paths_and_profile_file(tmp_path):
    profile = tmp_path / "p.json"
    profile.write_text(
        json.dumps({"facebook_url": "https://www.facebook.com/tmp.user", "display_name": "Lan Chi",
                    "bio": "Yêu mèo và trà chiều", "public_info": {"current_city": "Huế"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    code, out, _ = cli(tmp_path, "--url", "https://www.facebook.com/tmp.user", "--profile-file", str(profile),
                       "--output", "runs/a/out.json", "--evidence", "runs/a/ev.json")
    assert code == 0
    assert json.loads(out) == read(tmp_path / "runs" / "a" / "out.json")
    assert read(tmp_path / "runs" / "a" / "ev.json")["sources_used"] == ["profile_file"]
    assert not (tmp_path / "output.json").exists()


def test_private_profile_is_partial_exit_0(tmp_path):
    code, out, _ = cli(tmp_path, "--url", "https://www.facebook.com/fixture.private.user")
    assert code == 0 and json.loads(out)["error_note"].startswith("PRIVATE_PROFILE:")


def test_llm_mode_without_key(tmp_path):
    code, out, _ = cli(tmp_path, "--url", RICH_URL, "--mode", "llm")
    assert code == 2 and "ANTHROPIC_API_KEY" in json.loads(out)["error_note"]


def test_unwritable_output_still_prints_json_and_exit_1(tmp_path):
    (tmp_path / "taken").mkdir()
    code, out, err = cli(tmp_path, "--url", RICH_URL, "--output", "taken")
    assert code == 1
    assert json.loads(out)["status"] == "SUCCESS"
    assert "could not write output files" in err
