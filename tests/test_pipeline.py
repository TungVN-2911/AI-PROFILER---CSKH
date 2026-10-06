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


# --- Error matrix -------------------------------------------------------------------------------


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
    assert "chỉ hiển thị với bạn bè" in result.output.error_note
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
    assert "quá thời gian chờ" in result.output.error_note


def test_insufficient_data(tmp_path):
    path, url = write_profile(tmp_path, display_name="Chỉ Có Tên", bio="Yêu mèo")
    result = run(url, PipelineOptions(mode="deterministic", profile_file=path))
    assert_partial(result, "INSUFFICIENT_DATA:")
    assert result.evidence.access_state.value == "PUBLIC" and len(result.evidence.fact_ledger) == 2


def test_live_meta_bio_clauses_pass_sufficiency_gate_without_image():
    body = """<html><head>
    <meta property="og:title" content="Trinh Trinh | Facebook">
    <meta property="og:description" content="16.191 người theo dõi · 19.004 người đang nói về điều này. Người sáng tạo nội dung số">
    </head></html>"""
    result = run(
        "https://www.facebook.com/live.user",
        **live(lambda request: httpx.Response(200, text=body, headers={"content-type": "text/html"})),
    )
    assert_partial(result, "NO_IMAGE:")
    bio_facts = [fact for fact in result.evidence.fact_ledger if fact.category == "bio"]
    assert len(bio_facts) == 3
    assert [fact.statement for fact in bio_facts] == [
        "16.191 người theo dõi",
        "19.004 người đang nói về điều này",
        "Người sáng tạo nội dung số",
    ]


def test_explicit_profile_file_takes_precedence_over_live_fetch(tmp_path):
    path, url = write_profile(tmp_path, display_name="Dữ liệu đã cung cấp", bio="Yêu mèo")

    def fail_live_source(request):
        raise AssertionError(f"live source should not be called: {request.url}")

    result = run(
        url,
        PipelineOptions(mode="deterministic", profile_file=path, live=True),
        http_transport=httpx.MockTransport(fail_live_source),
    )
    assert result.evidence.sources_used == ["profile_file"]
    assert result.evidence.fact_ledger[0].statement == "Dữ liệu đã cung cấp"


FAKE_PNG = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + b"0000"
ENOUGH_FACTS = dict(display_name="Lan Chi", bio="Yêu mèo và trà chiều", public_info={"current_city": "Huế"})


def test_no_image_is_partial_no_image(tmp_path):
    path, url = write_profile(tmp_path, **ENOUGH_FACTS)
    result = run(url, PipelineOptions(mode="deterministic", profile_file=path))
    assert_partial(result, "NO_IMAGE:")
    assert "(không có ảnh công khai nào được cung cấp)" in result.output.error_note
    assert result.evidence.access_state.value == "PUBLIC" and len(result.evidence.fact_ledger) == 3


def test_undescribed_image_in_deterministic_mode_is_no_image(tmp_path):
    (tmp_path / "a.png").write_bytes(FAKE_PNG)
    path, url = write_profile(tmp_path, images=[{"kind": "avatar", "path": str(tmp_path / "a.png")}], **ENOUGH_FACTS)
    result = run(url, PipelineOptions(mode="deterministic", profile_file=path))
    assert_partial(result, "NO_IMAGE:")
    assert "chưa cấu hình mô hình đọc ảnh" in result.output.error_note


def test_unreadable_image_is_no_image(tmp_path):
    path, url = write_profile(tmp_path, images=[{"kind": "avatar", "path": str(tmp_path / "missing.jpg")}], **ENOUGH_FACTS)
    fake = FakeLLMClient()
    result = run(url, PipelineOptions(mode="auto", profile_file=path), llm_client=fake)
    assert_partial(result, "NO_IMAGE:")
    assert "không đọc được file ảnh" in result.output.error_note
    assert fake.calls == []  # nothing generated without a visual context


def test_all_vision_observations_rejected_is_no_image(tmp_path):
    (tmp_path / "a.png").write_bytes(FAKE_PNG)
    path, url = write_profile(tmp_path, images=[{"kind": "avatar", "path": str(tmp_path / "a.png")}], **ENOUGH_FACTS)
    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": [{"text": "appears to show a mother", "confidence": 0.9}]}])
    result = run(url, PipelineOptions(mode="auto", profile_file=path), llm_client=fake)
    assert_partial(result, "NO_IMAGE:")
    assert "không có quan sát ảnh nào qua được kiểm tra" in result.output.error_note


def test_accepted_vision_observation_allows_success(tmp_path):
    (tmp_path / "a.png").write_bytes(FAKE_PNG)
    path, url = write_profile(tmp_path, images=[{"kind": "avatar", "path": str(tmp_path / "a.png")}], **ENOUGH_FACTS)
    fake = FakeLLMClient(
        responses=[LLMError("timeout", "x")] * 3,
        vision_responses=[{"image_usable": True, "observations": [{"text": "appears to show a cat on a sofa", "confidence": 0.9}]}],
    )
    result = run(url, PipelineOptions(mode="auto", profile_file=path), llm_client=fake)
    assert isinstance(result.output, SuccessOutput)
    assert result.output.profile_data.visual_context.startswith("QUAN SÁT ẢNH BẰNG AI (ảnh đại diện")


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


# --- Extra input / configuration errors ---------------------------------------------------------


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


# --- Success path & evidence --------------------------------------------------------------------


def test_rich_fixture_success_deterministic_with_full_evidence():
    result = run("https://m.facebook.com/fixture.minh.anh/?ref=share")
    out, ev = result.output, result.evidence
    assert isinstance(out, SuccessOutput) and result.exit_code == 0
    assert out.facebook_url == RICH_URL
    assert out.profile_data.customer_name == "Nguyễn Minh Anh"
    assert out.profile_data.visual_context.startswith("MÔ TẢ ẢNH (từ dữ liệu được cung cấp):")
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
    assert any("chỉ đọc các thẻ meta HTML công khai" in n for n in result.evidence.technical_limitations)


def test_perceived_estimate_end_to_end_is_labelled_and_never_reaches_messages(tmp_path):
    (tmp_path / "a.png").write_bytes(FAKE_PNG)
    path, url = write_profile(
        tmp_path,
        images=[{"kind": "avatar", "path": str(tmp_path / "a.png"), "alt_text": "Ảnh đại diện có vẻ cho thấy một người cầm ô"}],
        **ENOUGH_FACTS,
    )
    estimate = {"single_person_visible": True, "perceived_gender": "female", "gender_confidence": 0.85,
                "age_min": 25, "age_max": 35, "age_confidence": 0.7}
    fake = FakeLLMClient(
        responses=[LLMError("timeout", "x")] * 3,
        vision_responses=[{"image_usable": True, "observations": [], "estimate": estimate}],
    )
    result = run(url, PipelineOptions(mode="auto", profile_file=path), llm_client=fake)
    out, ev = result.output, result.evidence
    assert isinstance(out, SuccessOutput)
    demo = out.profile_data.estimated_demographics
    assert demo.gender.startswith("INFERENCE: Nữ (ước lượng từ ảnh đại diện, độ tin cậy 0.85) [F")
    assert demo.estimated_age_range.startswith("INFERENCE: 25–35 tuổi (ước lượng từ ảnh đại diện")
    ledger = {f.id: f for f in ev.fact_ledger}
    assert [ledger[i].category for i in ev.grounding.gender] == ["perceived_gender"]
    assert [ledger[i].category for i in ev.grounding.estimated_age_range] == ["perceived_age"]
    # Estimates are never message material: not cited, not in any generation prompt.
    estimate_ids = set(ev.grounding.gender) | set(ev.grounding.estimated_age_range)
    assert not estimate_ids & {i for g in ev.grounding.messages for i in g.fact_ids}
    for call in fake.calls:
        if call["kind"] == "generate":
            assert "perceived" not in call["user"] and "female" not in call["user"]


def test_self_declared_female_fixture_uses_chi_em():
    result = run("https://www.facebook.com/fixture.khanh.linh")
    assert result.evidence.addressing.startswith("chị/em (giới tính tự khai báo")
    messages = result.output.ethical_rapport.dialogue_sequence_10
    assert messages[0].startswith("Em chào chị Khánh Linh")
    assert all(" bạn " not in f" {m} " for m in messages)


def test_unknown_gender_keeps_ban_minh():
    result = run(RICH_URL)
    assert result.evidence.addressing == "bạn/mình (chưa rõ giới tính)"
