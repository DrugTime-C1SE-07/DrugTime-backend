from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from drugtime.modules.medication.domain.health_setup import HealthSetup, SetupStep

AllergenId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ConditionId = Annotated[int, Field(strict=True, ge=1)]
CustomName = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[^\x00]+$")]


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


class HealthSetupRequest(StepModel):
    revision: str = Field(min_length=1, max_length=128)
    allergies: NoneKnown | Reported[AllergenId] | None = None
    conditions: NoneKnown | Reported[ConditionId] | None = None

    @model_validator(mode="after")
    def validate_steps(self):
        steps = self.model_fields_set & {"allergies", "conditions"}
        if not steps or any(getattr(self, step) is None for step in steps):
            raise ValueError("supply at least one step and omit skipped steps")
        return self


class HealthSetupResponse(StepModel):
    revision: str = Field(min_length=1, max_length=128)
    allergies: Unreported | NoneKnown | Reported[AllergenId]
    conditions: Unreported | NoneKnown | Reported[ConditionId]

    @classmethod
    def from_setup(cls, snapshot: HealthSetup):
        def encode(step):
            if step.status != "reported":
                return {"status": step.status}
            return {
                "status": step.status,
                "catalog_ids": list(step.catalog_ids),
                "custom_names": list(step.custom_names),
            }

        return cls.model_validate(
            {
                "revision": snapshot.revision,
                "allergies": encode(snapshot.allergies),
                "conditions": encode(snapshot.conditions),
            }
        )


def decode_step(step):
    if step is None:
        return None
    if isinstance(step, NoneKnown):
        return SetupStep("none_known")
    return SetupStep("reported", tuple(step.catalog_ids), tuple(step.custom_names))
