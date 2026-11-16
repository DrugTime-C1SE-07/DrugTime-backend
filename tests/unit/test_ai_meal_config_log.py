"""Log cấu hình hiệu lực khi khởi động và bí mật trong Settings (task 5.11: AC9, AC22)."""

import logging

from drugtime.main import create_app
from drugtime.modules.ai_meal import api as ai_meal
from drugtime.shared.config import Settings

LLM_KEY = "sk-ant-FAKE-llm-key"
PEXELS_KEY = "FAKE-pexels-key"


def _settings(**kw):
    return Settings(_env_file=None, llm_api_key=LLM_KEY, pexels_api_key=PEXELS_KEY, **kw)


def test_empty_url_logged_as_default_without_keys__AC22(caplog):
    caplog.set_level(logging.INFO, logger="drugtime.modules.ai_meal")
    ai_meal.log_effective_config(_settings(llm_api_url="", llm_model="claude-haiku-5-5",
                                           llm_timeout_seconds=20))
    (record,) = [r for r in caplog.records if "ai_meal config" in r.getMessage()]
    msg = record.getMessage()
    assert "llm_base_url=mặc định" in msg
    assert "llm_model=claude-haiku-5-5" in msg and "llm_timeout=20" in msg
    assert "refresh_daily_limit=2" in msg and "image_enabled=False" in msg
    assert LLM_KEY not in caplog.text and PEXELS_KEY not in caplog.text


def test_explicit_url_logged__AC22(caplog):
    caplog.set_level(logging.INFO, logger="drugtime.modules.ai_meal")
    ai_meal.log_effective_config(_settings(llm_api_url="https://proxy.example/v1"))
    assert "llm_base_url=https://proxy.example/v1" in caplog.text


def test_create_app_logs_config_once__AC22(caplog):
    caplog.set_level(logging.INFO, logger="drugtime.modules.ai_meal")
    create_app()
    assert caplog.text.count("ai_meal config") == 1


def test_settings_repr_hides_secrets__AC9():
    text = repr(_settings()) + str(_settings().model_dump())
    assert LLM_KEY not in text and PEXELS_KEY not in text
