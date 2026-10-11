"""Catalog HTTP response schemas, matching api_contract/openapi.json."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.domain.sync_run import (
    CatalogSyncRun,
    CatalogSyncRunPage,
    CatalogSyncSource,
    CatalogSyncStatus,
    CatalogSyncTrigger,
)


class CatalogMedicationSummary(BaseModel):
    id: int
    name: str
    active_ingredient: str | None
    strength_text: str | None
    dosage_form: str | None

    @classmethod
    def from_domain(cls, m: CatalogMedication) -> "CatalogMedicationSummary":
        return cls(
            id=m.id,
            name=m.name,
            active_ingredient=m.active_ingredient,
            strength_text=m.strength_text,
            dosage_form=m.dosage_form,
        )


class CatalogMedicationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CatalogMedicationSummary] = Field(max_length=50)


class CatalogSyncRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    source: CatalogSyncSource
    started_at: datetime
    finished_at: datetime | None
    status: CatalogSyncStatus
    records_inserted: int = Field(ge=0)
    records_updated: int = Field(ge=0)
    records_failed: int = Field(ge=0)
    error_details: dict[str, Any] | None
    triggered_by: CatalogSyncTrigger

    @classmethod
    def from_domain(cls, run: CatalogSyncRun) -> "CatalogSyncRunSummary":
        return cls(**run.__dict__)


class CatalogSyncRunList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CatalogSyncRunSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)

    @classmethod
    def from_domain(cls, page: CatalogSyncRunPage) -> "CatalogSyncRunList":
        return cls(
            items=[CatalogSyncRunSummary.from_domain(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
