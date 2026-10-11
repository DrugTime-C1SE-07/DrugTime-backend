"""Catalog synchronization run models and safe error reports."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

MAX_ERROR_SAMPLES = 20
MAX_SOURCE_REF_LENGTH = 200


class CatalogSyncSource(StrEnum):
    DAV_DRUGBANK = "dav_drugbank"
    DUOC_THU_QG = "duoc_thu_qg"


class CatalogSyncStatus(StrEnum):
    RUNNING = "dang_chay"
    SUCCEEDED = "thanh_cong"
    FAILED = "that_bai"


class CatalogSyncTrigger(StrEnum):
    SCHEDULER = "scheduler"
    ADMIN = "admin_thu_cong"


SAFE_ERROR_MESSAGES = {
    "invalid_record": "Catalog record is invalid",
    "database_record_error": "Catalog record could not be stored",
    "no_valid_records": "Catalog source returned no valid records",
    "invalid_payload": "Catalog source returned an invalid payload",
    "source_timeout": "Catalog source request timed out",
    "source_unavailable": "Catalog source is temporarily unavailable",
    "database_unavailable": "Catalog database is temporarily unavailable",
    "sync_failed": "Catalog synchronization failed",
}


@dataclass(frozen=True)
class CatalogSyncErrorSample:
    row_number: int
    code: str
    source_ref: str | None = None


@dataclass
class CatalogSyncErrorReport:
    groups: Counter[str] = field(default_factory=Counter)
    samples: list[CatalogSyncErrorSample] = field(default_factory=list)
    total: int = 0

    def add(self, code: str, row_number: int, source_ref: object = None) -> None:
        safe_code = code if code in SAFE_ERROR_MESSAGES else "sync_failed"
        self.total += 1
        self.groups[safe_code] += 1
        if len(self.samples) < MAX_ERROR_SAMPLES:
            ref = None if source_ref is None else str(source_ref)[:MAX_SOURCE_REF_LENGTH]
            self.samples.append(CatalogSyncErrorSample(row_number, safe_code, ref))

    def as_json(self, message_code: str | None = None) -> dict[str, Any] | None:
        if not self.total and message_code is None:
            return None
        code = message_code or "invalid_record"
        safe_code = code if code in SAFE_ERROR_MESSAGES else "sync_failed"
        result: dict[str, Any] = {
            "code": safe_code,
            "message": SAFE_ERROR_MESSAGES[safe_code],
        }
        if self.total:
            result.update(
                groups=[
                    {"code": group, "count": count}
                    for group, count in sorted(self.groups.items())
                ],
                samples=[
                    {
                        "row_number": sample.row_number,
                        "code": sample.code,
                        "source_ref": sample.source_ref,
                    }
                    for sample in self.samples
                ],
                samples_truncated=self.total > len(self.samples),
            )
        return result


def sanitize_error_details(value: object) -> dict[str, Any] | None:
    """Return only the bounded error shape safe for the Admin API."""
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    safe_code = code if isinstance(code, str) and code in SAFE_ERROR_MESSAGES else "sync_failed"
    result: dict[str, Any] = {
        "code": safe_code,
        "message": SAFE_ERROR_MESSAGES[safe_code],
    }
    groups = []
    for group in value.get("groups", []) if isinstance(value.get("groups"), list) else []:
        if not isinstance(group, dict):
            continue
        group_code, count = group.get("code"), group.get("count")
        if group_code in SAFE_ERROR_MESSAGES and isinstance(count, int) and count >= 0:
            groups.append({"code": group_code, "count": count})
    samples = []
    raw_samples = value.get("samples", []) if isinstance(value.get("samples"), list) else []
    for sample in raw_samples[:MAX_ERROR_SAMPLES]:
        if not isinstance(sample, dict):
            continue
        row_number, sample_code = sample.get("row_number"), sample.get("code")
        if (
            not isinstance(row_number, int)
            or row_number < 1
            or sample_code not in SAFE_ERROR_MESSAGES
        ):
            continue
        ref = sample.get("source_ref")
        samples.append(
            {
                "row_number": row_number,
                "code": sample_code,
                "source_ref": None if ref is None else str(ref)[:MAX_SOURCE_REF_LENGTH],
            }
        )
    if groups:
        result["groups"] = groups
    if samples:
        result["samples"] = samples
        result["samples_truncated"] = bool(value.get("samples_truncated")) or len(
            raw_samples
        ) > len(samples)
    return result


@dataclass(frozen=True)
class CatalogSyncRun:
    id: int
    source: CatalogSyncSource
    started_at: datetime
    finished_at: datetime | None
    status: CatalogSyncStatus
    records_inserted: int
    records_updated: int
    records_failed: int
    error_details: dict[str, Any] | None
    triggered_by: CatalogSyncTrigger


@dataclass(frozen=True)
class CatalogSyncRunPage:
    items: list[CatalogSyncRun]
    total: int
    limit: int
    offset: int
