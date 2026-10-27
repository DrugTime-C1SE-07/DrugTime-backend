import importlib

import httpx
import pytest
from celery.exceptions import Retry

from drugtime.modules.catalog import tasks as catalog_tasks
from drugtime.runtime import job_runner


@pytest.fixture
def mock_channel(monkeypatch):
    # .env của máy dev có thể đặt NOTIFICATION_CHANNEL=fcm; test không dùng credential thật.
    from drugtime.shared.config import get_settings

    monkeypatch.setenv("NOTIFICATION_CHANNEL", "mock")
    monkeypatch.setattr(job_runner, "_notifier", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_tick_is_registered_in_celery_beat(monkeypatch, mock_channel):
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")

    import drugtime.worker as worker

    worker = importlib.reload(worker)
    schedule = worker.celery_app.conf.beat_schedule["drugtime-periodic-tick"]
    assert schedule["task"] == "runtime.tick"
    assert schedule["schedule"] == float(worker.get_settings().tick_interval_seconds)

    heartbeat = worker.celery_app.conf.beat_schedule["drugtime-worker-heartbeat"]
    assert heartbeat == {"task": "runtime.heartbeat", "schedule": 60.0}
    assert worker.celery_app.conf.timezone == "Asia/Ho_Chi_Minh"


def test_celery_quota_friendly_configuration():
    conf = catalog_tasks.celery_app.conf

    assert conf.task_ignore_result is True
    assert conf.task_send_sent_event is False
    assert conf.worker_send_task_events is False
    assert conf.worker_enable_remote_control is False
    assert conf.worker_prefetch_multiplier == 1
    assert conf.broker_pool_limit == 1


def test_catalog_sync_task_uses_late_ack_and_rejects_worker_loss():
    assert catalog_tasks.sync_catalog.acks_late is True
    assert catalog_tasks.sync_catalog.reject_on_worker_lost is True
    assert catalog_tasks.sync_catalog.max_retries == 3
    assert catalog_tasks.sync_catalog.retry_backoff is True
    assert catalog_tasks.sync_catalog.retry_jitter is True


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_http_status_is_retryable(status):
    request = httpx.Request("POST", "https://dav.invalid")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("failed", request=request, response=response)

    assert catalog_tasks._is_transient_http_error(error)


@pytest.mark.parametrize("status", [400, 401, 404])
def test_permanent_http_status_is_not_retryable(status):
    request = httpx.Request("POST", "https://dav.invalid")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("failed", request=request, response=response)

    assert not catalog_tasks._is_transient_http_error(error)


def test_unsupported_catalog_source_is_not_wrapped_for_retry():
    with pytest.raises(ValueError, match="unsupported catalog source"):
        catalog_tasks.sync_catalog.run("unsupported")


def test_transport_error_is_wrapped_for_celery_retry(monkeypatch):
    retried = []

    def fail_sync(*_args, **_kwargs):
        request = httpx.Request("POST", "https://dav.invalid")
        raise httpx.ConnectError("temporarily unavailable", request=request)

    def retry(*, exc, **kwargs):
        retried.append((exc, kwargs))
        raise Retry()

    monkeypatch.setattr(catalog_tasks, "run_sync", fail_sync)
    monkeypatch.setattr(catalog_tasks.sync_catalog, "retry", retry)

    with pytest.raises(Retry):
        catalog_tasks.sync_catalog.run("dav_drugbank")

    assert isinstance(retried[0][0], catalog_tasks.TransientCatalogSyncError)
    assert "dav.invalid" not in str(retried[0][0])


def test_permanent_http_error_is_not_wrapped_for_retry(monkeypatch):
    request = httpx.Request("POST", "https://dav.invalid/private")
    response = httpx.Response(400, request=request)
    error = httpx.HTTPStatusError("bad request", request=request, response=response)

    def fail_sync(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(catalog_tasks, "run_sync", fail_sync)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        catalog_tasks.sync_catalog.run("dav_drugbank")

    assert caught.value is error


def test_tick_continues_after_each_step_failure(monkeypatch):
    calls = []

    def fail_scan():
        calls.append("scan")
        raise RuntimeError("scan failed")

    monkeypatch.setattr(job_runner, "_scan", fail_scan)
    monkeypatch.setattr(job_runner, "_sync_if_due", lambda: calls.append("sync"))
    monkeypatch.setattr(job_runner, "_resume_erasures", lambda: calls.append("erase"))

    job_runner.tick()

    assert calls == ["scan", "sync", "erase"]


def test_default_tick_interval_900__AC44(monkeypatch):
    from drugtime.shared.config import Settings

    monkeypatch.delenv("TICK_INTERVAL_SECONDS", raising=False)
    assert Settings(_env_file=None).tick_interval_seconds == 900


def test_heartbeat_calls_health_once__AC45(monkeypatch):
    calls = []
    monkeypatch.setattr(job_runner.health, "record_heartbeat", calls.append)

    job_runner.record_worker_heartbeat("x")

    assert calls == ["x"]


def test_worker_import_validates_notification_config__AC42(monkeypatch, mock_channel):
    from drugtime.notification_gateway import NotificationConfigError

    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setenv("NOTIFICATION_CHANNEL", "fcm")
    monkeypatch.setenv("FCM_CREDENTIALS_FILE", "")
    import drugtime.worker as worker

    with pytest.raises(NotificationConfigError, match="FCM_CREDENTIALS_FILE"):
        importlib.reload(worker)

    # Nạp lại bản dùng được để các test sau không thấy module worker dở dang.
    from drugtime.shared.config import get_settings

    monkeypatch.setenv("NOTIFICATION_CHANNEL", "mock")
    get_settings.cache_clear()
    importlib.reload(worker)


def test_gateway_is_built_once_and_reused(monkeypatch, mock_channel):
    built = []
    monkeypatch.setattr(
        job_runner.notification_gateway, "build", lambda settings: built.append(1) or object()
    )
    monkeypatch.setattr(job_runner.adherence, "scan_missed_doses", lambda uow, notifier: 0)

    job_runner._scan()
    job_runner._scan()

    assert built == [1]
