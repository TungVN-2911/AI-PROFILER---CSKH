"""Gemini adapter with a stubbed SDK client — no network."""

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.config import load_settings
from app.guardrails import EngagementDraft
from app.llm import get_llm_client
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMError, VisionResult
from app.llm.gemini_client import GeminiLLMClient, inline_schema

NO_KEY = load_settings(env={}, dotenv_path=None)
GEMINI = load_settings(env={"GEMINI_API_KEY": "test-gemini-key-not-real"}, dotenv_path=None)
BOTH = load_settings(env={"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, dotenv_path=None)


class Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    fact_ids: list[str]


class StubModels:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def stub(response=None, exc=None):
    return SimpleNamespace(models=StubModels(response, exc))


def reply(text, finish="STOP", block=None, with_thought=False):
    parts = [SimpleNamespace(text="(model reasoning)", thought=True)] if with_thought else []
    parts.append(SimpleNamespace(text=text, thought=None))
    candidate = SimpleNamespace(finish_reason=types.FinishReason[finish], content=SimpleNamespace(parts=parts))
    feedback = SimpleNamespace(block_reason=types.BlockedReason[block]) if block else None
    return SimpleNamespace(candidates=[candidate], prompt_feedback=feedback)


def adapter(sdk, settings=GEMINI):
    return GeminiLLMClient(settings, client=sdk)


def has_ref(node):
    if isinstance(node, dict):
        return "$ref" in node or "$defs" in node or any(has_ref(v) for v in node.values())
    if isinstance(node, list):
        return any(has_ref(v) for v in node)
    return False


# --- Request shape ------------------------------------------------------------------------------


def test_success_and_request_shape():
    sdk = stub(reply(json.dumps({"message": "chào chị", "fact_ids": ["F2"]}), with_thought=True))
    result = adapter(sdk).generate_structured(system="SYS", user="USER", output_model=Echo)
    assert result == Echo(message="chào chị", fact_ids=["F2"])  # thought parts are ignored
    kw = sdk.models.kwargs
    assert kw["model"] == "gemini-3.8-flash"
    assert kw["contents"] == ["USER"]
    config = kw["config"]
    assert config.system_instruction == "SYS"
    assert config.response_mime_type == "application/json"
    assert set(config.response_json_schema["required"]) == {"message", "fact_ids"}
    assert config.max_output_tokens == 16000


@pytest.mark.parametrize("model", [EngagementDraft, VisionResult])
def test_nested_schemas_are_inlined_without_refs(model):
    schema = inline_schema(TypeAdapter(model).json_schema())
    assert not has_ref(schema)
    assert schema["additionalProperties"] is False


def test_image_request_uses_inline_bytes():
    sdk = stub(reply(json.dumps({"image_usable": True, "observations": []})))
    result = adapter(sdk).describe_image(image_bytes=b"abc", media_type="image/jpeg", instructions="RULES")
    assert result.image_usable is True
    part = sdk.models.kwargs["contents"][0]
    assert part.inline_data.mime_type == "image/jpeg" and part.inline_data.data == b"abc"
    assert sdk.models.kwargs["config"].system_instruction == "RULES"


def test_unsupported_image_type_makes_no_call():
    sdk = stub()
    with pytest.raises(LLMError) as exc:
        adapter(sdk).describe_image(image_bytes=b"x", media_type="image/gif", instructions="i")
    assert exc.value.kind == "unsupported_input" and sdk.models.kwargs is None


# --- Response handling --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response,kind",
    [
        (reply("", finish="SAFETY"), "refusal"),
        (reply("", finish="PROHIBITED_CONTENT"), "refusal"),
        (reply('{"message": "cut', finish="MAX_TOKENS"), "max_tokens"),
        (reply("{}", block="SAFETY"), "refusal"),
        (SimpleNamespace(candidates=[], prompt_feedback=None), "invalid_output"),
        (reply("not json"), "invalid_output"),
        (reply(json.dumps({"message": "m"})), "invalid_output"),
        (reply("   "), "invalid_output"),
    ],
)
def test_finish_reasons_and_invalid_output(response, kind):
    with pytest.raises(LLMError) as exc:
        adapter(stub(response)).generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == kind


def _client_error(code, status):
    return errors.ClientError(code, {"error": {"code": code, "message": "m", "status": status}})


@pytest.mark.parametrize(
    "error,kind",
    [
        (_client_error(401, "UNAUTHENTICATED"), "auth"),
        (_client_error(403, "PERMISSION_DENIED"), "auth"),
        (_client_error(429, "RESOURCE_EXHAUSTED"), "rate_limited"),
        (_client_error(404, "NOT_FOUND"), "api_error"),
        (errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}), "api_error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "api_error"),
    ],
)
def test_sdk_errors_are_mapped(error, kind):
    with pytest.raises(LLMError) as exc:
        adapter(stub(exc=error)).generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == kind


# --- Construction & provider selection ----------------------------------------------------------


def test_requires_key_when_building_real_client():
    with pytest.raises(LLMError) as exc:
        GeminiLLMClient(NO_KEY)
    assert exc.value.kind == "no_credentials"


def test_real_client_builds_offline_with_key():
    client = GeminiLLMClient(GEMINI)  # network guard (conftest) proves construction makes no request
    assert client.model_id == "gemini-3.8-flash"


def test_factory_picks_gemini_when_only_gemini_key():
    assert isinstance(get_llm_client(GEMINI, "auto"), GeminiLLMClient)
    assert GEMINI.resolved_provider == "gemini" and GEMINI.active_model == "gemini-3.8-flash"


def test_factory_auto_prefers_claude_when_both_keys():
    assert isinstance(get_llm_client(BOTH, "auto"), AnthropicLLMClient)


def test_factory_explicit_gemini_provider():
    settings = load_settings(env={"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a", "LLM_PROVIDER": "gemini"}, dotenv_path=None)
    assert isinstance(get_llm_client(settings, "auto"), GeminiLLMClient)


def test_explicit_provider_without_its_key():
    settings = load_settings(env={"ANTHROPIC_API_KEY": "a", "LLM_PROVIDER": "gemini"}, dotenv_path=None)
    assert get_llm_client(settings, "auto") is None
    with pytest.raises(LLMError) as exc:
        get_llm_client(settings, "llm")
    assert "GEMINI_API_KEY" in exc.value.detail and "LLM_PROVIDER=gemini" in exc.value.detail


def test_gemini_model_and_provider_configurable_and_key_hidden():
    settings = load_settings(env={"GEMINI_API_KEY": "secret-gemini-123", "GEMINI_MODEL": "gemini-3.5-flash-lite"}, dotenv_path=None)
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert "secret-gemini-123" not in repr(settings)


# --- Model fallback chain -----------------------------------------------------------------------


class ChainModels:
    """Per-model behaviour: an exception to raise or a response to return; records the call order."""

    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs["model"])
        outcome = self.behaviour[kwargs["model"]]
        if isinstance(outcome, Exception):
            raise outcome
        self.last_config = kwargs["config"]
        return outcome


OVERLOADED = errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
OK = reply(json.dumps({"message": "ok", "fact_ids": []}))


def chain_client(behaviour, env=None):
    settings = load_settings(env={"GEMINI_API_KEY": "k", **(env or {})}, dotenv_path=None)
    models = ChainModels(behaviour)
    return GeminiLLMClient(settings, client=SimpleNamespace(models=models)), models


def test_default_chain_and_dedupe():
    assert GEMINI.gemini_model_chain == ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
    s = load_settings(env={"GEMINI_MODEL": "a", "GEMINI_FALLBACK_MODELS": " b , a ,, c "}, dotenv_path=None)
    assert s.gemini_model_chain == ["a", "b", "c"]


def test_overloaded_primary_falls_back_and_is_skipped_afterwards():
    client, models = chain_client({"gemini-3.8-flash": OVERLOADED, "gemini-3.5-flash": OVERLOADED, "gemini-3.5-flash-lite": OK})
    assert client.generate_structured(system="s", user="u", output_model=Echo).message == "ok"
    assert models.calls == ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
    assert client.model_id == "gemini-3.5-flash-lite"
    client.generate_structured(system="s", user="u", output_model=Echo)
    assert models.calls[3:] == ["gemini-3.5-flash-lite"]  # failed models are not retried in the same run


@pytest.mark.parametrize("error", [_client_error(429, "RESOURCE_EXHAUSTED"), _client_error(404, "NOT_FOUND"), httpx.ReadTimeout("slow")])
def test_quota_missing_model_and_timeout_fall_back(error):
    client, models = chain_client({"gemini-3.8-flash": error, "gemini-3.5-flash": OK, "gemini-3.5-flash-lite": OK})
    client.generate_structured(system="s", user="u", output_model=Echo)
    assert models.calls == ["gemini-3.8-flash", "gemini-3.5-flash"] and client.model_id == "gemini-3.5-flash"


def test_auth_error_does_not_fall_back():
    client, models = chain_client({"gemini-3.8-flash": _client_error(401, "UNAUTHENTICATED"), "gemini-3.5-flash": OK, "gemini-3.5-flash-lite": OK})
    with pytest.raises(LLMError) as exc:
        client.generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == "auth" and models.calls == ["gemini-3.8-flash"]


def test_all_models_unavailable_raises_last_error():
    client, models = chain_client({m: OVERLOADED for m in GEMINI.gemini_model_chain})
    with pytest.raises(LLMError) as exc:
        client.generate_structured(system="s", user="u", output_model=Echo)
    assert exc.value.kind == "api_error" and len(models.calls) == 3
    with pytest.raises(LLMError):
        client.generate_structured(system="s", user="u", output_model=Echo)
    assert len(models.calls) == 3  # nothing left to try, no further requests


def test_afc_disabled_in_request_config():
    client, models = chain_client({"gemini-3.8-flash": OK, "gemini-3.5-flash": OK, "gemini-3.5-flash-lite": OK})
    client.generate_structured(system="s", user="u", output_model=Echo)
    assert models.last_config.automatic_function_calling.disable is True


def test_generation_records_the_serving_model():
    from app.generation.llm_generator import generate_engagement
    from tests.test_guardrails import CLEAN, LEDGER

    client, _ = chain_client({"gemini-3.8-flash": OVERLOADED, "gemini-3.5-flash": reply(json.dumps(CLEAN)), "gemini-3.5-flash-lite": OK})
    result = generate_engagement(LEDGER, load_settings(env={}, dotenv_path=None), client)
    assert result.mode == "llm" and result.model_id == "gemini-3.5-flash"
