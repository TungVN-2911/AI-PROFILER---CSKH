import json

import httpx
import pytest

import app.pipeline as pipeline
from app.config import load_settings
from app.guardrails import Violation
from app.llm.base import LLMError
from app.llm.fake import FakeLLMClient
from app.pipeline import PipelineOptions, run_pipeline
from app.schema import PartialOutput, SuccessOutput, parse_output, to_json_dict
from tests.test_guardrails import CLEAN

SETTINGS = load_settings(env={}, dotenv_path=None)
RICH_URL = "https://www.facebook.com/fixture.minh.anh"
DET = PipelineOptions(mode="deterministic")


def run(url, options=DET, **kwargs):
    result = run_pipeline(url, options, SETTINGS, **kwargs)
    # Every path must produce a strict-schema, JSON-serialisable output.
    doc = json.loads(json.dumps(to_json_dict(result.output), ensure_ascii=False))
    assert type(parse_output(doc)) is type(result.output)
    json.loads(result.evidence.model_dump_json())
    return result


def write_profile(tmp_path, url="https://www.facebook.com/tmp.user", **fields):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"facebook_url": url, **fields}, ensure_ascii=False), encoding="utf-8")
    return path, url


def live(handler):
    return dict(options=PipelineOptions(mode="deterministic", live=True), http_transport=httpx.MockTransport(handler))


def assert_partial(result, prefix, exit_code=0):
    assert isinstance(result.output, PartialOutput)
    assert result.output.error_note.startswith(prefix), result.output.error_note
    assert result.exit_code == exit_code
    assert result.evidence.output_status == "PARTIAL_OR_PRIVATE"


# --- Error matrix (architecture.md §6) ------------------------------------------------------


@pytest.mark.parametrize("url", [None, "", "   "])
def test_missing_url(url):
    result = run(url)
    assert_partial(result, "INVALID_INPUT:", 2)
    assert result.output.facebook_url == (url or "")


@pytest.mark.parametrize("url", ["https://www.facebook.com/groups/123", "https://example.com/user", "not a url"])
def test_non_profile_url(url):
    result = run(url)
    assert_partial(result, "INVALID_INPUT:", 2)
    assert result.output.facebook_url == url
    assert result.evidence.access_state.value == "INVALID_INPUT"


def test_no_provided_data_live_disabled():
    result = run("https://www.facebook.com/nobody.anywhere")
    assert_partial(result, "TECHNICAL LIMITATION:")
    assert "--profile-file" in result.output.error_note
    assert result.evidence.access_state.value == "NO_ACCESSIBLE_DATA"


def test_live_login_wall():
    result = run("https://www.facebook.com/nobody.anywhere", **live(lambda r: httpx.Response(302, headers={"location": "https://www.facebook.com/login/"})))
    assert_partial(result, "TECHNICAL LIMITATION:")
    assert result.evidence.access_state.value == "LOGIN_REQUIRED"


def test_private_profile_fixture():
    result = run("https://www.facebook.com/fixture.private.user")
    assert_partial(result, "PRIVATE_PROFILE:")
    assert "restricted to friends" in result.output.error_note
    assert "Trần Hoài Nam" not in result.output.model_dump_json()  # name in file is not used
    assert result.evidence.synthetic_data is True and result.evidence.fact_ledger == []


def test_dead_link_live_404():
    result = run("https://www.facebook.com/nobody.anywhere", **live(lambda r: httpx.Response(404)))
    assert_partial(result, "NOT_FOUND:")
    assert "HTTP 404" in result.output.error_note


def test_dead_link_provided_data(tmp_path):
    path, url = write_profile(tmp_path, access={"state": "NOT_FOUND", "note": "Link returns 'content isn't available'."})
    assert_partial(run(url, PipelineOptions(mode="deterministic", profile_file=path)), "NOT_FOUND:")


def test_unreachable_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    result = run("https://www.facebook.com/nobody.anywhere", **live(handler))
    assert_partial(result, "UNREACHABLE:")
    assert "timed out" in result.output.error_note


def test_insufficient_data(tmp_path):
    path, url = write_profile(tmp_path, display_name="Chỉ Có Tên", bio="Yêu mèo")
    result = run(url, PipelineOptions(mode="deterministic", profile_file=path))
    assert_partial(result, "INSUFFICIENT_DATA:")
    assert result.evidence.access_state.value == "PUBLIC" and len(result.evidence.fact_ledger) == 2


def test_no_image_is_success_with_visual_not_available(tmp_path):
    path, url = write_profile(tmp_path, display_name="Lan Chi", bio="Yêu mèo và trà chiều", public_info={"current_city": "Huế"})
    result = run(url, PipelineOptions(mode="deterministic", profile_file=path))
    assert isinstance(result.output, SuccessOutput) and result.exit_code == 0
    assert result.output.profile_data.visual_context == "NOT_AVAILABLE: no public image provided"


def test_llm_failure_after_retries_is_success_via_deterministic():
    fake = FakeLLMClient(responses=[LLMError("timeout", "slow")] * 3)
    result = run(RICH_URL, PipelineOptions(mode="auto"), llm_client=fake)
    assert isinstance(result.output, SuccessOutput)
    assert result.evidence.generation_mode == "deterministic"
    assert result.evidence.model_id == "fake-llm"
    assert result.evidence.validation.attempts == 4  # 3 LLM + 1 deterministic
    assert len(result.evidence.validation.violations) >= 3


def test_unexpected_exception_is_internal_error(monkeypatch):
    def boom(raw):
        raise KeyError("bug")

    monkeypatch.setattr(pipeline, "build_ledger", boom)
    result = run(RICH_URL)
    assert_partial(result, "INTERNAL_ERROR:", 1)
    assert result.output.facebook_url == RICH_URL


# --- Extra input / configuration errors -----------------------------------------------------


def test_llm_mode_without_key_is_configuration_error():
    result = run(RICH_URL, PipelineOptions(mode="llm"))
    assert_partial(result, "TECHNICAL LIMITATION:", 2)
    assert "ANTHROPIC_API_KEY" in result.output.error_note


def test_malformed_profile_file_is_invalid_input(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert_partial(run(RICH_URL, PipelineOptions(mode="deterministic", profile_file=bad)), "INVALID_INPUT:", 2)


def test_profile_file_for_other_url_is_invalid_input(tmp_path):
    path, _ = write_profile(tmp_path, url="https://www.facebook.com/someone.else", display_name="X")
    assert_partial(run(RICH_URL, PipelineOptions(mode="deterministic", profile_file=path)), "INVALID_INPUT:", 2)


# --- Success path & evidence ---------------------------------------------------------------


def test_rich_fixture_success_deterministic_with_full_evidence():
    result = run("https://m.facebook.com/fixture.minh.anh/?ref=share")
    out, ev = result.output, result.evidence
    assert isinstance(out, SuccessOutput) and result.exit_code == 0
    assert out.facebook_url == RICH_URL
    assert out.profile_data.customer_name == "Nguyễn Minh Anh"
    assert out.profile_data.visual_context.startswith("PROVIDED IMAGE DESCRIPTION:")
    assert out.profile_data.estimated_demographics.gender == "UNKNOWN"
    assert out.profile_data.estimated_demographics.estimated_age_range == "UNKNOWN"
    assert out.profile_data.estimated_demographics.apparent_lifestyle.startswith("INFERENCE:")
    assert len(out.ethical_rapport.dialogue_sequence_10) == 10
    assert out.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"
    assert out.evening_cadence_20pm.trigger_time == "20:00"

    assert ev.generation_mode == "deterministic" and ev.model_id is None
    assert ev.synthetic_data is True and ev.sources_used == ["profile_store"]
    assert ev.validation.passed is True
    # Grounding covers every message, and every cited id exists in the ledger.
    assert [g.index for g in ev.grounding.messages] == list(range(len(out.ethical_rapport.dialogue_sequence_10)))
    ids = {f.id for f in ev.fact_ledger}
    cited = {i for g in ev.grounding.messages for i in g.fact_ids}
    cited |= set(ev.grounding.evening_hook) | set(ev.grounding.core_empathy_angle) | set(ev.grounding.apparent_lifestyle)
    assert cited <= ids
    assert ev.grounding.evening_hook and ev.grounding.core_empathy_angle


def test_llm_success_uses_llm_draft_and_validated_lifestyle():
    llm_draft = {**CLEAN, "apparent_lifestyle": {"text": "INFERENCE: thích vận động và làm bánh (F5, F6)", "fact_ids": ["F5", "F6"]}}
    result = run(RICH_URL, PipelineOptions(mode="auto"), llm_client=FakeLLMClient(responses=[llm_draft]))
    out, ev = result.output, result.evidence
    assert isinstance(out, SuccessOutput)
    assert ev.generation_mode == "llm" and ev.validation.attempts == 1
    assert out.ethical_rapport.dialogue_sequence_10 == [m["text"] for m in CLEAN["messages"]]
    assert out.profile_data.estimated_demographics.apparent_lifestyle.startswith("INFERENCE: thích vận động")
    assert ev.grounding.apparent_lifestyle == ["F5", "F6"]


def test_deterministic_mode_ignores_injected_llm():
    fake = FakeLLMClient(responses=[CLEAN])
    result = run(RICH_URL, DET, llm_client=fake)
    assert result.evidence.generation_mode == "deterministic" and fake.calls == []


def test_zero_sales_confirmation_only_after_final_validation(monkeypatch):
    monkeypatch.setattr(pipeline, "validate_draft", lambda draft, ledger: [Violation("SALES_TERM", "messages[0]", "x")])
    result = run(RICH_URL)
    assert not isinstance(result.output, SuccessOutput)
    assert "ZERO_SALES_CONFIRMED" not in result.output.model_dump_json()
    assert_partial(result, "INTERNAL_ERROR:", 1)


def test_live_public_profile_end_to_end():
    html = (
        '<meta property="og:title" content="Lê Thu Hà | Facebook">'
        '<meta property="og:description" content="Giáo viên tiếng Anh, mê đọc sách.">'
    )
    result = run(
        "https://www.facebook.com/fixture.live.user",
        **live(lambda r: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=html)),
    )
    # Name + one description fact is below the default gate (2 usable facts) → honest PARTIAL.
    assert_partial(result, "INSUFFICIENT_DATA:")
    assert result.evidence.sources_used == ["live_meta"]
    assert any("only public HTML meta tags" in n for n in result.evidence.technical_limitations)
