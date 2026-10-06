from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, ConfigError, load_settings

SECRET = "sk-ant-test-not-a-real-key-123"


def load(env=None, **kwargs):
    return load_settings(env=env or {}, dotenv_path=None, **kwargs)


def test_defaults_with_empty_environment():
    s = load()
    assert s.anthropic_api_key is None
    assert s.has_llm_credentials is False
    assert s.llm_model == "claude-opus-5-5"
    assert s.llm_timeout_seconds == 60
    assert s.llm_max_retries == 2
    assert s.output_language == "vi"
    assert s.live_fetch_enabled is False
    assert s.profile_store_dir == PROJECT_ROOT / "fixtures" / "profiles"
    assert s.min_grounding_facts == 2
    assert s.default_message_count == 10


def test_env_overrides_defaults():
    s = load(
        {
            "ANTHROPIC_API_KEY": SECRET,
            "LLM_MODEL": "claude-sonnet-5-5",
            "LLM_TIMEOUT_SECONDS": "30",
            "LLM_MAX_RETRIES": "1",
            "OUTPUT_LANGUAGE": "en",
            "LIVE_FETCH_ENABLED": "true",
            "PROFILE_STORE_DIR": "other/profiles",
            "MIN_GROUNDING_FACTS": "3",
            "DEFAULT_MESSAGE_COUNT": "7",
        }
    )
    assert s.has_llm_credentials is True
    assert s.anthropic_api_key.get_secret_value() == SECRET
    assert s.llm_model == "claude-sonnet-5-5"
    assert s.llm_timeout_seconds == 30
    assert s.llm_max_retries == 1
    assert s.output_language == "en"
    assert s.live_fetch_enabled is True
    assert s.profile_store_dir == PROJECT_ROOT / "other" / "profiles"
    assert s.min_grounding_facts == 3
    assert s.default_message_count == 7


@pytest.mark.parametrize("raw,expected", [("1", True), ("yes", True), ("false", False), ("0", False)])
def test_boolean_parsing(raw, expected):
    assert load({"LIVE_FETCH_ENABLED": raw}).live_fetch_enabled is expected


def test_empty_values_are_treated_as_unset():
    s = load({"ANTHROPIC_API_KEY": "", "LLM_MODEL": "  "})
    assert s.has_llm_credentials is False
    assert s.llm_model == "claude-opus-5-5"


def test_overrides_take_precedence_over_env():
    s = load({"LIVE_FETCH_ENABLED": "false"}, overrides={"live_fetch_enabled": True})
    assert s.live_fetch_enabled is True


@pytest.mark.parametrize(
    "var,value",
    [
        ("DEFAULT_MESSAGE_COUNT", "4"),
        ("DEFAULT_MESSAGE_COUNT", "11"),
        ("MIN_GROUNDING_FACTS", "0"),
        ("LIVE_FETCH_ENABLED", "maybe"),
        ("LLM_TIMEOUT_SECONDS", "-5"),
        ("OUTPUT_LANGUAGE", "vietnamese"),
    ],
)
def test_invalid_values_raise_clear_error(var, value):
    with pytest.raises(ConfigError) as exc:
        load({var: value})
    assert var in str(exc.value)


def test_api_key_never_in_repr_or_str():
    s = load({"ANTHROPIC_API_KEY": SECRET})
    assert SECRET not in repr(s)
    assert SECRET not in str(s)
    assert SECRET not in s.model_dump_json()


def test_dotenv_file_is_read_and_env_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("PROFILER_NO_DOTENV", raising=False)  # conftest disables .env for every other test
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_MAX_RETRIES=0\nDEFAULT_MESSAGE_COUNT=6\n", encoding="utf-8")
    s = load_settings(env={"DEFAULT_MESSAGE_COUNT": "8"}, dotenv_path=dotenv)
    assert s.llm_max_retries == 0
    assert s.default_message_count == 8


def test_config_module_does_not_import_provider_sdk():
    import app.config as config

    source = Path(config.__file__).read_text(encoding="utf-8")
    assert "import anthropic" not in source


def test_provider_defaults_and_validation():
    s = load({})
    assert s.llm_provider == "auto" and s.gemini_model == "gemini-3.8-flash"
    assert s.resolved_provider is None and s.active_model is None
    with pytest.raises(ConfigError) as exc:
        load({"LLM_PROVIDER": "openai"})
    assert "LLM_PROVIDER" in str(exc.value)


def test_profiler_no_dotenv_ignores_env_file(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=real-key-from-file", encoding="utf-8")
    monkeypatch.setenv("PROFILER_NO_DOTENV", "1")
    assert load_settings(env={}, dotenv_path=dotenv).gemini_api_key is None
    monkeypatch.delenv("PROFILER_NO_DOTENV")
    assert load_settings(env={}, dotenv_path=dotenv).gemini_api_key.get_secret_value() == "real-key-from-file"
