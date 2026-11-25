"""Adapter cache Redis gợi ý bữa ăn (task 5.09 AC3, AC8, AC13)."""

import logging
from unittest.mock import MagicMock

import pytest
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from drugtime.modules.ai_meal.adapters.outbound.redis_meal_cache import (
    RedisMealCache,
    build_client,
)

KEY = "meal_cache:" + "a" * 64
RAW = '{"meals": ["Canh chua cá"]}'
URL = "rediss://default:FAKE-upstash-token@cache.example:6379"
LOGGER = "drugtime.modules.ai_meal.adapters.outbound.redis_meal_cache"
ERRORS = [ConnectionError("cache.example:6379 refused"), TimeoutError("t"),
          ResponseError("ERR max requests limit exceeded")]


def test_get_returns_stored_value():
    client = MagicMock()
    client.get.return_value = RAW
    assert RedisMealCache(client, 60).get(KEY) == RAW
    client.get.assert_called_once_with(KEY)


def test_get_miss_returns_none():
    client = MagicMock()
    client.get.return_value = None
    assert RedisMealCache(client, 60).get(KEY) is None


def test_put_sets_ttl__AC3():
    client = MagicMock()
    RedisMealCache(client, 604800).put(KEY, RAW)
    client.set.assert_called_once_with(KEY, RAW, ex=604800)


@pytest.mark.parametrize("ttl", [0, -1])
def test_non_positive_ttl_rejected__AC3(ttl):
    with pytest.raises(ValueError):
        RedisMealCache(MagicMock(), ttl)


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_get_error_returns_none_and_logs_kind__AC8_AC13(caplog, error):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    client = MagicMock()
    client.get.side_effect = error
    assert RedisMealCache(client, 60).get(KEY) is None
    assert f"ai_meal cache event=error op=get kind={type(error).__name__}" in caplog.text


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_put_error_swallowed_and_logged__AC8_AC13(caplog, error):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    client = MagicMock()
    client.set.side_effect = error
    RedisMealCache(client, 60).put(KEY, RAW)  # không raise
    assert f"ai_meal cache event=error op=set kind={type(error).__name__}" in caplog.text


def test_log_has_no_key_url_or_value__AC13(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    client = MagicMock()
    client.get.side_effect = ERRORS[0]
    client.set.side_effect = ERRORS[2]
    cache = RedisMealCache(client, 60)
    cache.get(KEY)
    cache.put(KEY, RAW)
    for secret in (KEY, "FAKE-upstash-token", "cache.example", "Canh chua", "max requests"):
        assert secret not in caplog.text


def test_client_built_without_retry_and_with_timeout__AC8():
    client = build_client(URL, 1.0)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 1.0 and kwargs["socket_connect_timeout"] == 1.0
    assert client.get_retry()._retries == 0
    assert kwargs["decode_responses"] is True
