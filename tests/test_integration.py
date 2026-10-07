"""End-to-end tests organised by the brief's test matrix (§24). Offline; no API key.

CLI cases run `main.py` as a subprocess. AI cases run the real pipeline in-process with a scripted fake LLM,
since a subprocess cannot be given a fake client.
"""

import copy
import json
import os
import re
import subprocess
import sys

import pytest

from app.config import PROJECT_ROOT, load_settings
from app.lexicons import (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    PRICE_PATTERN,
    URL_PATTERN,
    find_presumptions,
    find_sales_terms,
)
from app.llm.base import LLMError
from app.llm.fake import FakeLLMClient
from app.pipeline import PipelineOptions, run_pipeline
from app.schema import PartialOutput, SuccessOutput, parse_output
from tests.test_guardrails import CLEAN

MAIN = PROJECT_ROOT / "main.py"
SETTINGS = load_settings(env={}, dotenv_path=None)
RICH = "https://www.facebook.com/fixture.minh.anh"

FIXTURE_URLS = {
    "public": RICH,
    "public_no_image": "https://www.facebook.com/fixture.quoc.bao",
    "declared": "https://www.facebook.com/fixture.khanh.linh",
    "profile_id": "https://www.facebook.com/profile.php?id=100000000000042",
    "partial": "https://www.facebook.com/fixture.thu.ha",
    "name_only": "https://www.facebook.com/fixture.name.only",
    "private": "https://www.facebook.com/fixture.private.user",
    "dead": "https://www.facebook.com/fixture.dead.link",
}


def _env():
    blocked = ("ANTHROPIC_", "GEMINI_", "PYTHONIOENCODING", "PYTHONUTF8", "LLM_", "LIVE_", "PROFILE_STORE", "MIN_GROUNDING",
               "DEFAULT_MESSAGE", "OUTPUT_LANGUAGE")
    return {k: v for k, v in os.environ.items() if not k.startswith(blocked)}


def cli(tmp_path, *args):
    proc = subprocess.run([sys.executable, str(MAIN), *args], cwd=tmp_path, env=_env(), capture_output=True, timeout=60)
    stdout = proc.stdout.decode("utf-8")
    doc = json.loads(stdout)  # stdout must be exactly one JSON document
    file_doc = json.loads((tmp_path / "output.json").read_text(encoding="utf-8"))
    assert doc == file_doc, "stdout and output.json differ"
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    return proc.returncode, parse_output(doc), evidence


# --- Independent invariants (do not reuse the guardrail code paths) -----------------------------


def assert_zero_sales(texts):
    # Prices, links and contact details are never allowed (commercial words are checked against citations below).
    for text in texts:
        for pattern in (PRICE_PATTERN, URL_PATTERN, PHONE_PATTERN, EMAIL_PATTERN):
            assert not pattern.search(text), f"{pattern.pattern!r} matched in: {text}"
        assert "#" not in text


def assert_success_invariants(out: SuccessOutput, evidence: dict):
    messages = out.ethical_rapport.dialogue_sequence_10
    assert 5 <= len(messages) <= 10
    assert out.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"
    assert out.evening_cadence_20pm.trigger_time == "20:00"
    texts = [*messages, out.evening_cadence_20pm.evening_hook_message, out.ethical_rapport.core_empathy_angle]
    assert_zero_sales(texts)

    ledger = {f["id"]: f for f in evidence["fact_ledger"]}
    cited_text = {g["index"]: " ".join(ledger[i]["statement"] for i in g["fact_ids"]) for g in evidence["grounding"]["messages"]}
    for i, text in enumerate(messages):
        for term in find_sales_terms(text):
            assert term.casefold() in cited_text[i].casefold(), f"unsupported commercial term {term!r} in message {i}"
        for phrase in find_presumptions(text):
            assert phrase.casefold() in cited_text[i].casefold(), f"presumption {phrase!r} in message {i}"

    # Demographic honesty: UNKNOWN, derived from a self-declared fact, or a labelled perceived INFERENCE.
    demo = out.profile_data.estimated_demographics
    assert demo.gender == "UNKNOWN" or "tự khai báo" in demo.gender or (
        demo.gender.startswith("INFERENCE:") and "ước lượng từ" in demo.gender)
    assert demo.estimated_age_range == "UNKNOWN" or "tính từ năm sinh tự khai báo" in demo.estimated_age_range or (
        demo.estimated_age_range.startswith("INFERENCE:") and "ước lượng từ" in demo.estimated_age_range)
    assert demo.apparent_lifestyle == "UNKNOWN" or demo.apparent_lifestyle.startswith("INFERENCE:")

    # Evidence: every message grounded or neutral, every cited id exists and is a FACT.
    grounding = evidence["grounding"]
    assert [g["index"] for g in grounding["messages"]] == list(range(len(messages)))
    cited = [i for g in grounding["messages"] for i in g["fact_ids"]] + grounding["evening_hook"] + grounding["core_empathy_angle"]
    assert all(ledger[i]["epistemic_status"] == "FACT" for i in cited)
    assert grounding["evening_hook"] and grounding["core_empathy_angle"]
    assert evidence["validation"]["passed"] is True


# --- Input --------------------------------------------------------------------------------------


def test_input_valid_url(tmp_path):
    code, out, evidence = cli(tmp_path, "--url", RICH)
    assert code == 0 and isinstance(out, SuccessOutput)
    assert_success_invariants(out, evidence)


@pytest.mark.parametrize("url", ["https://www.facebook.com/groups/123456", "https://evil.example/fixture.minh.anh", "hello"])
def test_input_invalid_url(tmp_path, url):
    code, out, evidence = cli(tmp_path, "--url", url)
    assert code == 2 and isinstance(out, PartialOutput)
    assert out.error_note.startswith("INVALID_INPUT:") and out.facebook_url == url
    assert evidence["access_state"] == "INVALID_INPUT"


def test_input_missing_url(tmp_path):
    code, out, _ = cli(tmp_path)
    assert code == 2 and out.error_note.startswith("INVALID_INPUT:")


# --- Data availability --------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["public", "declared", "profile_id", "partial"])
def test_data_success_cases(tmp_path, case):
    code, out, evidence = cli(tmp_path, "--url", FIXTURE_URLS[case])
    assert code == 0 and isinstance(out, SuccessOutput)
    assert_success_invariants(out, evidence)
    assert evidence["synthetic_data"] is True
    if case == "partial":
        assert evidence["access_state"] == "PARTIAL"


@pytest.mark.parametrize(
    "case,prefix,state",
    [
        ("private", "PRIVATE_PROFILE:", "PRIVATE"),
        ("dead", "NOT_FOUND:", "NOT_FOUND"),
        ("name_only", "INSUFFICIENT_DATA:", "PUBLIC"),
        ("public_no_image", "NO_IMAGE:", "PUBLIC"),
    ],
)
def test_data_partial_cases(tmp_path, case, prefix, state):
    code, out, evidence = cli(tmp_path, "--url", FIXTURE_URLS[case])
    assert code == 0 and isinstance(out, PartialOutput)
    assert out.error_note.startswith(prefix)
    assert evidence["access_state"] == state


def test_data_unknown_profile_reports_technical_limitation(tmp_path):
    code, out, _ = cli(tmp_path, "--url", "https://www.facebook.com/someone.not.provided", "--no-live")
    assert code == 0 and out.error_note.startswith("TECHNICAL LIMITATION:")


# --- AI -----------------------------------------------------------------------------------------


def _llm_run(responses):
    fake = FakeLLMClient(responses=responses)
    return run_pipeline(RICH, PipelineOptions(mode="auto"), SETTINGS, llm_client=fake), fake


def test_ai_valid_structured_output_is_used():
    result, fake = _llm_run([CLEAN])
    assert isinstance(result.output, SuccessOutput)
    assert result.evidence.generation_mode == "llm"
    assert result.output.ethical_rapport.dialogue_sequence_10 == [m["text"] for m in CLEAN["messages"]]
    assert len(fake.calls) == 1


@pytest.mark.parametrize("bad", ["not json at all", {"messages": []}, LLMError("invalid_output", "schema")])
def test_ai_invalid_output_falls_back_to_valid_deterministic(bad):
    result, fake = _llm_run([bad] * 3)
    assert isinstance(result.output, SuccessOutput)
    assert result.evidence.generation_mode == "deterministic"
    assert len(fake.calls) == 3


def test_ai_hallucination_is_rejected_and_never_emitted():
    hallucinated = copy.deepcopy(CLEAN)
    hallucinated["messages"][1]["text"] = "Nghe nói bạn vừa về nhất giải marathon Đà Lạt 42km, chúc mừng nha!"
    hallucinated["evening_hook"]["text"] = "Chắc bạn vừa đi làm về mệt lắm, nghỉ ngơi đi nhé!"
    result, _ = _llm_run([hallucinated] * 3)
    out = result.output
    assert isinstance(out, SuccessOutput) and result.evidence.generation_mode == "deterministic"
    emitted = json.dumps(out.model_dump(), ensure_ascii=False)
    assert "Đà Lạt" not in emitted and "42km" not in emitted and "đi làm về" not in emitted
    codes = " ".join(result.evidence.validation.violations)
    assert "UNGROUNDED_ENTITY" in codes and "UNGROUNDED_NUMBER" in codes and "PRESUMPTION" in codes


def test_ai_missing_information_stays_unknown():
    result, fake = _llm_run([CLEAN])
    demo = result.output.profile_data.estimated_demographics
    assert demo.gender == "UNKNOWN" and demo.estimated_age_range == "UNKNOWN"
    prompt = fake.calls[0]["user"]
    assert "Unknown fields (never mention or guess): hometown, pronouns, gender, birth_year." in prompt


def test_ai_sales_from_llm_never_reaches_output():
    salesy = copy.deepcopy(CLEAN)
    salesy["messages"][9]["text"] = "Bên mình có khóa học làm bánh giảm 30%, inbox để nhận ưu đãi nhé!"
    result, _ = _llm_run([salesy] * 3)
    emitted = json.dumps(result.output.model_dump(), ensure_ascii=False)
    assert "ưu đãi" not in emitted and "30%" not in emitted and "inbox" not in emitted
    assert result.output.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"


# --- Rapport ------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [5, 10])
def test_rapport_message_counts(tmp_path, n):
    code, out, evidence = cli(tmp_path, "--url", RICH, "--messages", str(n))
    assert code == 0 and len(out.ethical_rapport.dialogue_sequence_10) == n
    assert_success_invariants(out, evidence)


def test_rapport_zero_sales_across_all_success_fixtures(tmp_path):
    for case in ("public", "declared", "profile_id", "partial"):
        result = run_pipeline(FIXTURE_URLS[case], PipelineOptions(mode="deterministic"), SETTINGS)
        assert_success_invariants(result.output, json.loads(result.evidence.model_dump_json()))


# --- Output -------------------------------------------------------------------------------------


def test_output_is_valid_json_schema_stdout_and_file(tmp_path):
    proc = subprocess.run([sys.executable, str(MAIN), "--url", RICH], cwd=tmp_path, env=_env(), capture_output=True, timeout=60)
    stdout = proc.stdout.decode("utf-8")
    assert stdout.count('"status"') == 1  # a single document
    doc = json.loads(stdout)
    assert isinstance(parse_output(doc), SuccessOutput)
    raw_file = (tmp_path / "output.json").read_text(encoding="utf-8")
    assert json.loads(raw_file) == doc
    assert set(doc) == {"status", "facebook_url", "profile_data", "ethical_rapport", "evening_cadence_20pm"}
    assert not re.search(r"\\u[0-9a-f]{4}", raw_file)  # Vietnamese stored as UTF-8, not escaped


def test_brand_never_reaches_output_end_to_end():
    branded = copy.deepcopy(CLEAN)
    branded["evening_hook"]["text"] = "Tối nay chị thử dầu gội Dr.Bee phục hồi nang tóc nhé!"
    result, _ = _llm_run([branded] * 3)
    emitted = json.dumps(result.output.model_dump(), ensure_ascii=False)
    assert "Dr.Bee" not in emitted and "nang tóc" not in emitted and "dầu gội" not in emitted
    assert result.output.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"
