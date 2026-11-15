"""LLM_API_KEY không lộ qua repr/str của cấu hình (task 4.26, AC3)."""

from drugtime.shared.config import Settings

KEY = "sk-ant-test-0123456789abcdef"


def test_llm_api_key_not_in_repr__AC3(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", KEY)
    settings = Settings(_env_file=None)
    assert settings.llm_api_key.get_secret_value() == KEY
    assert KEY not in repr(settings)
    assert KEY not in str(settings)
    assert KEY not in settings.model_dump_json()


def test_llm_defaults_disabled_with_budget():
    settings = Settings(_env_file=None)
    assert settings.ai_meal_llm_enabled is False
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.llm_model == "claude-sonnet-5-5"
    assert settings.llm_timeout_seconds == 8.0
