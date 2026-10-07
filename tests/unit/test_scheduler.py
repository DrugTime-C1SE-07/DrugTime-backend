import importlib

import httpx
import pytest
from celery.exceptions import Retry

from drugtime.modules.catalog import tasks as catalog_tasks
from drugtime.runtime import job_runner


def test_tick_is_registered_in_celery_beat(monkeypatch):
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
