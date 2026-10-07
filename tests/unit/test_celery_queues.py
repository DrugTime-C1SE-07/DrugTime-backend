from types import SimpleNamespace
from uuid import UUID

from drugtime.modules.catalog.adapters.outbound import job_queue as catalog_queue
from drugtime.modules.consent.adapters.outbound import job_queue as consent_queue


def test_catalog_sync_is_sent_to_celery(monkeypatch):
    sent = []
    monkeypatch.setattr(
        catalog_queue.celery_app,
        "send_task",
        lambda name, args, kwargs: sent.append((name, args, kwargs))
        or SimpleNamespace(id="catalog-job"),
    )

    assert catalog_queue.enqueue_sync("dav_drugbank") == "catalog-job"
    assert sent == [
        ("catalog.sync", ["dav_drugbank"], {"triggered_by": "admin_thu_cong"})
    ]


def test_scheduled_catalog_sync_contains_only_source_and_trigger(monkeypatch):
    sent = []
    monkeypatch.setattr(
        catalog_queue.celery_app,
        "send_task",
        lambda name, args, kwargs: sent.append((name, args, kwargs))
        or SimpleNamespace(id="scheduled-job"),
    )

    assert (
        catalog_queue.enqueue_sync("dav_drugbank", triggered_by="scheduler")
        == "scheduled-job"
    )
    assert sent == [("catalog.sync", ["dav_drugbank"], {"triggered_by": "scheduler"})]


def test_erasure_is_sent_to_celery(monkeypatch):
    request_id = UUID("00000000-0000-0000-0000-000000000001")
    sent = []
    monkeypatch.setattr(
        consent_queue.celery_app,
        "send_task",
        lambda name, args: sent.append((name, args)) or SimpleNamespace(id="erasure-job"),
    )

    assert consent_queue.enqueue_erasure(request_id) == "erasure-job"
    assert sent == [("consent.erasure", [str(request_id)])]
