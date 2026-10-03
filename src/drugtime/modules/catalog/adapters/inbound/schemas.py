"""Response của /catalog/medications, khớp api_contract/openapi.json."""

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.catalog.domain.medication import CatalogMedication


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
