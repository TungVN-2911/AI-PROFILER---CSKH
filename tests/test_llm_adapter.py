import json
import re
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict

from app.config import PROJECT_ROOT, load_settings
from app.llm import get_llm_client
from app.llm.anthropic_client import FALLBACK_BETA, AnthropicLLMClient
from app.llm.base import LLMError, VisionResult
from app.llm.fake import FakeLLMClient

NO_KEY = load_settings(env={}, dotenv_path=None)
WITH_KEY = load_settings(env={"ANTHROPIC_API_KEY": "sk-ant-test-not-real"}, dotenv_path=None)


class Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    fact_ids: list[str]


# --- Provider isolation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,allowed",
    [
        (r"^\s*(import anthropic|from anthropic)\b", "anthropic_client.py"),
        (r"^\s*(import google|from google)\b", "gemini_client.py"),
    ],
)
def test_only_the_adapter_imports_its_provider_sdk(pattern, allowed):
    regex = re.compile(pattern, re.MULTILINE)
    offenders = [
        str(p.relative_to(PROJECT_ROOT))
        for p in (PROJECT_ROOT / "app").rglob("*.py")
        if regex.search(p.read_text(encoding="utf-8")) and p.name != allowed
    ]
    assert offenders == []


# --- Factory ------------------------------------------------------------------------------------


def test_factory_deterministic_mode_returns_none_even_with_key():
    assert get_llm_client(WITH_KEY, "deterministic") is None


def test_factory_auto_without_key_returns_none():
    assert get_llm_client(NO_KEY, "auto") is None


def test_factory_llm_mode_without_key_raises():
    with pytest.raises(LLMError) as exc:
        get_llm_client(NO_KEY, "llm")
    assert exc.value.kind == "no_credentials"


def test_factory_auto_with_key_builds_claude_adapter():
    client = get_llm_client(WITH_KEY, "auto")
    assert isinstance(client, AnthropicLLMClient)
    assert client.model_id == "claude-opus-5-5"


# --- Fake client --------------------------------------------------------------------------------


def test_fake_success_from_dict_json_and_model():
    fake = FakeLLMClient(
        responses=[
            {"message": "a", "fact_ids": ["F1"]},
            json.dumps({"message": "b", "fact_ids": []}),
            Echo(message="c", fact_ids=["F2"]),
        ]
    )
    assert [fake.generate_structured(system="s", user="u", output_model=Echo).message for _ in range(3)] == ["a", "b", "c"]
    assert len(fake.calls) == 3 and fake.calls[0]["system"] == "s"


@pytest.mark.parametrize("bad", [{"message": "x"}, "{not json", {"message": "x", "fact_ids": [], "extra": 1}])
def test_fake_invalid_schema_raises_invalid_output(bad):
    with pytest.raises(LLMError) as exc:
        FakeLLMClient(responses=[bad]).generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == "invalid_output"


def test_fake_raises_queued_error_and_exhaustion():
    fake = FakeLLMClient(responses=[LLMError("refusal", "declined")])
    with pytest.raises(LLMError) as exc:
        fake.generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == "refusal"
    with pytest.raises(LLMError) as exc:
        fake.generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == "api_error"


def test_fake_vision():
    fake = FakeLLMClient(vision_responses=[{"image_usable": True, "observations": [{"text": "appears to show a bicycle", "confidence": 0.9}]}])
    result = fake.describe_image(image_bytes=b"\x89PNG", media_type="image/png", instructions="i")
    assert isinstance(result, VisionResult) and result.observations[0].confidence == 0.9


# --- Claude adapter with a stubbed SDK client ---------------------------------------------------


class StubSDK:
    def __init__(self, response=None, exc=None):
        self.response, self.exc = response, exc
        self.kwargs = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def reply(text, stop_reason="end_turn", **extra):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        model="claude-opus-5-5",
        **extra,
    )


def adapter(stub, settings=WITH_KEY):
    return AnthropicLLMClient(settings, client=stub)


def test_adapter_success_and_request_shape():
    stub = StubSDK(reply(json.dumps({"message": "xin chào", "fact_ids": ["F2"]})))
    result = adapter(stub).generate_structured(system="SYS", user="USER", output_model=Echo)
    assert result == Echo(message="xin chào", fact_ids=["F2"])
    kw = stub.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"] == "SYS"
    assert kw["messages"] == [{"role": "user", "content": [{"type": "text", "text": "USER"}]}]
    assert kw["fallbacks"] == "default" and kw["betas"] == [FALLBACK_BETA]
    assert kw["output_config"]["effort"] == "medium"
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"message", "fact_ids"}
    assert "thinking" not in kw and "temperature" not in kw


def test_adapter_omits_fallbacks_for_other_models():
    settings = load_settings(env={"ANTHROPIC_API_KEY": "k", "LLM_MODEL": "claude-haiku-4-5"}, dotenv_path=None)
    stub = StubSDK(reply(json.dumps({"message": "m", "fact_ids": []})))
    adapter(stub, settings).generate_structured(system="s", user="u", output_model=Echo)
    assert "fallbacks" not in stub.kwargs and "betas" not in stub.kwargs
    assert "effort" not in stub.kwargs["output_config"]


def test_adapter_image_request():
    stub = StubSDK(reply(json.dumps({"image_usable": True, "observations": []})))
    result = adapter(stub).describe_image(image_bytes=b"abc", media_type="image/jpeg", instructions="RULES")
    assert result.image_usable is True
    content = stub.kwargs["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "YWJj"}}
    assert stub.kwargs["system"] == "RULES"


def test_adapter_rejects_unsupported_image_type_without_calling_api():
    stub = StubSDK()
    with pytest.raises(LLMError) as exc:
        adapter(stub).describe_image(image_bytes=b"x", media_type="image/bmp", instructions="i")
    assert exc.value.kind == "unsupported_input" and stub.kwargs is None


@pytest.mark.parametrize(
    "response,kind",
    [
        (reply("", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")), "refusal"),
        (reply('{"message": "cut', stop_reason="max_tokens"), "max_tokens"),
        (reply("not json"), "invalid_output"),
        (reply(json.dumps({"message": "m"})), "invalid_output"),
        (reply("   "), "invalid_output"),
    ],
)
def test_adapter_stop_reasons_and_invalid_output(response, kind):
    with pytest.raises(LLMError) as exc:
        adapter(StubSDK(response)).generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == kind


REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "error,kind",
    [
        (anthropic.APITimeoutError(request=REQ), "timeout"),
        (anthropic.APIConnectionError(request=REQ), "api_error"),
        (anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=REQ), body=None), "auth"),
        (anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=REQ), body=None), "rate_limited"),
        (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=REQ), body=None), "api_error"),
        (anthropic.BadRequestError("bad", response=httpx2.Response(400, request=REQ), body=None), "api_error"),
    ],
)
def test_adapter_maps_sdk_errors(error, kind):
    with pytest.raises(LLMError) as exc:
        adapter(StubSDK(exc=error)).generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == kind


def test_adapter_requires_key_when_building_real_client():
    with pytest.raises(LLMError) as exc:
        AnthropicLLMClient(NO_KEY)
    assert exc.value.kind == "no_credentials"


def test_adapter_records_the_model_that_answered():
    stub = StubSDK(reply(json.dumps({"message": "m", "fact_ids": []})))
    stub.response.model = "claude-opus-4-8"  # e.g. a server-side refusal fallback answered
    client = adapter(stub)
    client.generate_structured(system="s", user="u", output_model=Echo)
    assert client.model_id == "claude-opus-4-8"
