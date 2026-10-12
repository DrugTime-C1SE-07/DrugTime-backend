"""Catalog HTTP response schemas, matching api_contract/openapi.json."""

from datetime import datetime
from typing import Any
"""Schemas của catalog module:
1. Response của /catalog/medications (Mobile K04, khớp api_contract/openapi.json).
2. Request/Response của /admin/medications (Admin CRUD PB04).
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.domain.sync_run import (
    CatalogSyncRun,
    CatalogSyncRunPage,
    CatalogSyncSource,
    CatalogSyncStatus,
    CatalogSyncTrigger,
)


# --- Mobile Catalog Search (K04) ---


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
# --- Admin Catalog CRUD (PB04) ---


class MedicationBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    raw_active_ingredient: str | None = Field(default=None, max_length=500)
    strength_text: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)
    manufacturer_name: str | None = Field(default=None, max_length=255)
    manufacturer_country: str | None = Field(default=None, max_length=100)
    packaging_spec: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, pattern="^(dav_drugbank|qd_5948|duoc_thu_qg)$")
    source_ref: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _source_pair(self) -> "MedicationBase":
        """source và source_ref phải cùng có giá trị hoặc cùng NULL (CHECK (source IS NULL)=(source_ref IS NULL))."""
        if (self.source is None) != (self.source_ref is None):
            raise ValueError("source and source_ref must both be null or both set")
        return self


class MedicationCreate(MedicationBase):
    pass


class MedicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    raw_active_ingredient: str | None = Field(default=None, max_length=500)
    strength_text: str | None = None
    dosage_form: str | None = None
    manufacturer_name: str | None = None
    manufacturer_country: str | None = None
    packaging_spec: str | None = None
    source: str | None = Field(default=None, pattern="^(dav_drugbank|qd_5948|duoc_thu_qg)$")
    source_ref: str | None = None

    @model_validator(mode="after")
    def _source_pair(self) -> "MedicationUpdate":
        if self.source is not None or self.source_ref is not None:
            if (self.source is None) != (self.source_ref is None):
                raise ValueError("source and source_ref must both be null or both set")
        return self


class MedicationResponse(MedicationBase):
    id: int
    deleted_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class MedicationListResponse(BaseModel):
    total: int
    items: list[MedicationResponse]


# --- Admin tra cứu hoạt chất (task 2.16) ---


class ActiveIngredientSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    standard_name: str
    atc_code: str | None
    pharmacological_group: str | None
    aliases: list[str]


class ActiveIngredientPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid", title="ActiveIngredientPage")

    items: list[ActiveIngredientSummary] = Field(max_length=100)
    total: int = Field(ge=0)

    @classmethod
    def from_domain(cls, page) -> "ActiveIngredientPageOut":  # page: ActiveIngredientPage
        return cls(
            items=[
                ActiveIngredientSummary(
                    id=i.id,
                    standard_name=i.standard_name,
                    atc_code=i.atc_code,
                    pharmacological_group=i.pharmacological_group,
                    aliases=i.aliases,
                )
                for i in page.items
            ],
            total=page.total,
        )
