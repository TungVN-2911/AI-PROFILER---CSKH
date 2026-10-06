import httpx
import pytest

from app.config import PROJECT_ROOT
from app.ledger import build_ledger
from app.lexicons import find_sensitive
from app.llm.base import LLMError
from app.llm.fake import FakeLLMClient
from app.models import EpistemicStatus, RawProfile
from app.sources.provided import load_raw_profile
from app.vision import NO_IMAGE, VISION_INSTRUCTIONS, extract_visual_context

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def raw(**kwargs):
    return RawProfile.model_validate({"facebook_url": "https://www.facebook.com/x.y.z", "display_name": "A", **kwargs})


def run(profile, llm=None, **kwargs):
    return extract_visual_context(profile, build_ledger(profile), llm, **kwargs)


def obs(text, confidence=0.9):
    return {"text": text, "confidence": confidence}


def local_image_profile(tmp_path, name="avatar.png"):
    (tmp_path / name).write_bytes(PNG)
    return raw(images=[{"kind": "avatar", "path": name}])


# --- No image / alt text --------------------------------------------------------------------


def test_no_image_is_not_available():
    result = run(raw())
    assert result.visual_context == NO_IMAGE == "NOT_AVAILABLE: no public image provided"
    assert result.fact_ids == []
    assert run(None).visual_context == NO_IMAGE


def test_provided_alt_text_used_without_llm_call():
    profile = load_raw_profile(PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json")
    fake = FakeLLMClient()
    result = run(profile, fake)
    assert result.visual_context.startswith("PROVIDED IMAGE DESCRIPTION: Ảnh đại diện có vẻ cho thấy")
    assert fake.calls == []
    fact = result.ledger.get(result.fact_ids[0])
    assert fact.epistemic_status is EpistemicStatus.FACT and fact.source.endswith(".alt_text")


def test_sensitive_alt_text_is_removed_from_ledger():
    profile = raw(images=[{"kind": "avatar", "alt_text": "A mother of two smiling with her kids"}])
    result = run(profile)
    assert result.visual_context.startswith("NOT_AVAILABLE")
    assert all(f.category != "visual_observation" for f in result.ledger.facts)
    assert "sensitive" in result.notes[0]


# --- Vision model path ----------------------------------------------------------------------


def test_valid_observations_become_inference_facts_with_vision_source(tmp_path):
    fake = FakeLLMClient(
        vision_responses=[
            {
                "image_usable": True,
                "observations": [obs("appears to show a person holding a coffee cup"), obs("appears to show a bicycle", 0.8)],
            }
        ]
    )
    profile = local_image_profile(tmp_path)
    before = build_ledger(profile)
    result = extract_visual_context(profile, before, fake, base_dir=tmp_path)

    assert result.visual_context.startswith("AI VISUAL OBSERVATION (avatar image, model-generated, unverified):")
    assert "coffee cup" in result.visual_context and "bicycle" in result.visual_context
    added = [result.ledger.get(fid) for fid in result.fact_ids]
    assert [f.source for f in added] == ["vision:avatar", "vision:avatar"]
    assert all(f.epistemic_status is EpistemicStatus.INFERENCE for f in added)
    assert [f.confidence for f in added] == [0.9, 0.8]
    assert {f.id for f in before.facts} < result.ledger.ids()
    # Model-generated observations are not usable for message grounding.
    assert not set(result.fact_ids) & {f.id for f in result.ledger.usable_facts()}
    call = fake.calls[0]
    assert call["media_type"] == "image/png" and call["instructions"] == VISION_INSTRUCTIONS


@pytest.mark.parametrize(
    "text,category",
    [
        ("appears to show a mother of two at a park", "family_relationship"),
        ("appears to show an Asian person smiling", "ethnicity"),
        ("appears to show a woman in her 30s", "gender_age_guess"),
        ("appears to show a pregnant person", "health_body"),
        ("appears to show a person wearing a hijab", "religion"),
        ("có vẻ là một phụ nữ đang cười", "gender_age_guess"),
    ],
)
def test_sensitive_observations_are_rejected(tmp_path, text, category):
    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": [obs(text), obs("appears to show a guitar")]}])
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), fake, base_dir=tmp_path)
    assert "guitar" in result.visual_context
    assert text not in result.visual_context
    assert len(result.fact_ids) == 1
    assert any(category in n for n in result.notes)


def test_low_confidence_and_unhedged_observations_rejected(tmp_path):
    fake = FakeLLMClient(
        vision_responses=[{"image_usable": True, "observations": [obs("appears to show a cat", 0.3), obs("a sunny beach")]}]
    )
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), fake, base_dir=tmp_path)
    assert result.visual_context == "NOT_AVAILABLE: no image observation passed validation"
    assert len(result.notes) == 2
    assert result.fact_ids == []


def test_image_not_usable(tmp_path):
    fake = FakeLLMClient(vision_responses=[{"image_usable": False, "observations": []}])
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), fake, base_dir=tmp_path)
    assert result.visual_context == "NOT_AVAILABLE: the image shows nothing describable"


def test_more_than_five_observations_is_invalid_output(tmp_path):
    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": [obs(f"appears to show item {i}") for i in range(6)]}])
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), fake, base_dir=tmp_path)
    assert result.visual_context == "NOT_AVAILABLE: vision analysis failed (invalid_output)"


def test_llm_error_is_not_available(tmp_path):
    fake = FakeLLMClient(vision_responses=[LLMError("timeout", "slow")])
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), fake, base_dir=tmp_path)
    assert result.visual_context == "NOT_AVAILABLE: vision analysis failed (timeout)"


def test_image_without_llm_in_deterministic_mode(tmp_path):
    result = extract_visual_context(local_image_profile(tmp_path), build_ledger(raw()), None, base_dir=tmp_path)
    assert "no vision model is configured" in result.visual_context


@pytest.mark.parametrize(
    "images,fragment",
    [
        ([{"kind": "avatar", "path": "missing.png"}], "could not be read"),
        ([{"kind": "avatar", "path": "avatar.bmp"}], "unsupported image file type"),
    ],
)
def test_local_image_problems(tmp_path, images, fragment):
    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": []}])
    result = extract_visual_context(raw(images=images), build_ledger(raw()), fake, base_dir=tmp_path)
    assert result.visual_context.startswith("NOT_AVAILABLE:") and fragment in result.visual_context
    assert fake.calls == []


# --- Image URL ------------------------------------------------------------------------------


def url_profile():
    return raw(images=[{"kind": "avatar", "url": "https://scontent.example/avatar.jpg"}])


def test_image_url_is_downloaded_once_and_described():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8\xff" + b"0" * 10)

    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": [obs("appears to show a mountain trail")]}])
    result = extract_visual_context(url_profile(), build_ledger(raw()), fake, transport=httpx.MockTransport(handler))
    assert "mountain trail" in result.visual_context
    assert len(requests) == 1 and "cookie" not in requests[0].headers
    assert fake.calls[0]["media_type"] == "image/jpeg"


@pytest.mark.parametrize(
    "response,fragment",
    [
        (httpx.Response(403), "HTTP 403"),
        (httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"), "unsupported content type"),
    ],
)
def test_image_url_failures(response, fragment):
    fake = FakeLLMClient()
    result = extract_visual_context(url_profile(), build_ledger(raw()), fake, transport=httpx.MockTransport(lambda r: response))
    assert result.visual_context.startswith("NOT_AVAILABLE:") and fragment in result.visual_context
    assert fake.calls == []


# --- Lexicon --------------------------------------------------------------------------------


def test_lexicon_word_boundaries():
    assert find_sensitive("appears to show a mango") == []  # "man" inside a word
    assert find_sensitive("appears to show a person running") == []
    assert ("gender_age_guess", "man") in find_sensitive("appears to show a man")
    assert find_sensitive("Ảnh đại diện có vẻ cho thấy một người mặc đồ chạy bộ, đeo số áo, đứng cạnh vạch đích.") == []
