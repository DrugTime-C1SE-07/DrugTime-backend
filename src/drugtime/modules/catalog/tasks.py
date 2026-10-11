"""Thin Celery wrappers for catalog application services."""

import httpx
from sqlalchemy.exc import OperationalError

from drugtime.modules.catalog.fetchers import fetch_dav_drugbank_pages
from drugtime.modules.catalog.parsers.dav_drugbank import parse
from drugtime.modules.catalog.service import run_sync
from drugtime.shared.celery import celery_app
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work


class TransientCatalogSyncError(RuntimeError):
    """Retryable transport or database failure during catalog synchronization."""


def _is_transient_http_error(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 429 or exc.response.status_code >= 500


@celery_app.task(
    name="catalog.sync",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(TransientCatalogSyncError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sync_catalog(
    source: str | None = None,
    triggered_by: str = "scheduler",
) -> None:
    settings = get_settings()
    source = source or "dav_drugbank"
    if source != "dav_drugbank":
        raise ValueError(f"unsupported catalog source: {source}")
    try:
        run_sync(
            unit_of_work,
            source=source,
            fetch=lambda: fetch_dav_drugbank_pages(settings.catalog_dav_drugbank_url),
            parse=parse,
            triggered_by=triggered_by,
        )
    except httpx.HTTPStatusError as exc:
        if _is_transient_http_error(exc):
            raise TransientCatalogSyncError("catalog source is temporarily unavailable") from exc
        raise
    except (httpx.TransportError, OperationalError) as exc:
        raise TransientCatalogSyncError("catalog dependency is temporarily unavailable") from exc
