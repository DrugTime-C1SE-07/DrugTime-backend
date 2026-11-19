from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from drugtime.modules.medication.domain.health_setup import (
    MAX_ALLERGY_NAME,
    MAX_CONDITION_NAME,
    AllergenLabel,
    HealthSetup,
    SetupStep,
)

AllergenId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ConditionId = Annotated[int, Field(strict=True, ge=1)]
CustomName = Annotated[
    str, Field(min_length=1, max_length=MAX_CONDITION_NAME, pattern=r"^[^\x00]+$")
]
AllergyName = Annotated[
    str, Field(min_length=1, max_length=MAX_ALLERGY_NAME, pattern=r"^[^\x00]+$")
]


class StepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Unreported(StepModel):
    status: Literal["unreported"]


class NoneKnown(StepModel):
    status: Literal["none_known"]


class Reported[CatalogId: (int, str)](StepModel):
    status: Literal["reported"]
    catalog_ids: list[CatalogId]
    custom_names: list[CustomName] = Field(max_length=30)

    @model_validator(mode="after")
    def validate_selection(self):
        if not self.catalog_ids and not self.custom_names:
            raise ValueError("reported requires at least one selection")
        if len(set(self.catalog_ids)) != len(self.catalog_ids):
            raise ValueError("catalog IDs must be unique")
        if len(set(self.custom_names)) != len(self.custom_names):
            raise ValueError("custom names must be unique")
        return self


class ReportedPhysiological(StepModel):
    """Physiological states are catalog-only: no custom names."""

    status: Literal["reported"]
    catalog_ids: list[ConditionId] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.catalog_ids)) != len(self.catalog_ids):
            raise ValueError("catalog IDs must be unique")
        return self


class AllergenCatalogItem(StepModel):
    id: AllergenId
    category: Literal["drug", "food"]
    name: str = Field(min_length=1)


class ReportedAllergySelection(Reported[AllergenId]):
    custom_names: list[AllergyName] = Field(max_length=30)


class ReportedAllergies(ReportedAllergySelection):
    """Response only: labels for every stored allergen id, in catalog_ids order."""

    catalog_items: list[AllergenCatalogItem] = Field(json_schema_extra={"uniqueItems": True})


class MissingAllergenLabel(RuntimeError):
    """A stored allergen id has no catalog row; never answer with a partial snapshot."""


class HealthSetupRequest(StepModel):
    revision: str = Field(min_length=1, max_length=128)
    allergies: NoneKnown | ReportedAllergySelection | None = None
    conditions: NoneKnown | Reported[ConditionId] | None = None
    physiological_states: NoneKnown | ReportedPhysiological | None = None

    @model_validator(mode="after")
    def validate_steps(self):
        steps = self.model_fields_set & {"allergies", "conditions", "physiological_states"}
        if not steps or any(getattr(self, step) is None for step in steps):
            raise ValueError("supply at least one step and omit skipped steps")
        return self


class HealthSetupResponse(StepModel):
    revision: str = Field(min_length=1, max_length=128)
    allergies: Unreported | NoneKnown | ReportedAllergies
    conditions: Unreported | NoneKnown | Reported[ConditionId]
    physiological_states: Unreported | NoneKnown | ReportedPhysiological

    @classmethod
    def from_setup(cls, snapshot: HealthSetup, labels: dict[str, AllergenLabel]):
        def encode(step):
            if step.status != "reported":
                return {"status": step.status}
            return {
                "status": step.status,
                "catalog_ids": list(step.catalog_ids),
                "custom_names": list(step.custom_names),
            }

        allergies = encode(snapshot.allergies)
        if snapshot.allergies.status == "reported":
            missing = [i for i in snapshot.allergies.catalog_ids if i not in labels]
            if missing:
                # No ids in the message: they are the patient's health data.
                raise MissingAllergenLabel(f"{len(missing)} stored allergen id(s) without label")
            allergies["catalog_items"] = [
                {"id": label.id, "category": label.category, "name": label.name}
                for label in (labels[i] for i in snapshot.allergies.catalog_ids)
            ]
        return cls.model_validate(
            {
                "revision": snapshot.revision,
                "allergies": allergies,
                "conditions": encode(snapshot.conditions),
                "physiological_states": (
                    {
                        "status": "reported",
                        "catalog_ids": list(snapshot.physiological_states.catalog_ids),
                    }
                    if snapshot.physiological_states.status == "reported"
                    else {"status": snapshot.physiological_states.status}
                ),
            }
        )


def decode_step(step):
    if step is None:
        return None
    if isinstance(step, NoneKnown):
        return SetupStep("none_known")
    return SetupStep("reported", tuple(step.catalog_ids), tuple(getattr(step, "custom_names", ())))
