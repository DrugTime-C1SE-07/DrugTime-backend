"""Schema HTTP của danh mục quy tắc tương tác (task 2.16), khớp api_contract/openapi.json.

Tên lớp trùng tên schema trong contract. Field lạ bị từ chối (`extra="forbid"`), nên client không
gửi được `verification_status` hay đổi cặp hoạt chất khi sửa.
"""

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from drugtime.modules.interaction.application.manage_rules import RuleView
from drugtime.modules.interaction.domain.catalog_rules import (
    VERIFICATION_STATUS,
    DoseThreshold,
    DrugFoodInteractionContent,
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    RecordState,
)

SeverityLevel = Annotated[int, Field(ge=1, le=4)]
MinIntervalHours = Annotated[float, Field(gt=0, le=168)]
Dose = Annotated[float, Field(ge=0)]


def _text(max_length: int):
    return Annotated[str, StringConstraints(min_length=1, max_length=max_length, pattern=r"\S")]


def _reject_nulls(model: BaseModel, nullable: set[str]) -> None:
    """Field không cho null mà client gửi `null` → 422 (contract không khai báo kiểu null)."""
    for name in model.model_fields_set - nullable:
        if getattr(model, name) is None:
            raise ValueError(f"{name} must not be null")


class DoseThresholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_ref: Literal["A", "B"]
    min_dose: Dose | None = None
    max_dose: Dose | None = None
    dose_unit: _text(50)
    severity_level: SeverityLevel
    warning_text: _text(1000)

    @model_validator(mode="after")
    def _range_present(self) -> "DoseThresholdInput":
        if not {"min_dose", "max_dose"} & self.model_fields_set:
            raise ValueError("min_dose or max_dose is required")
        return self

    def to_domain(self) -> DoseThreshold:
        return DoseThreshold(
            ingredient_ref=self.ingredient_ref,
            min_dose=self.min_dose,
            max_dose=self.max_dose,
            dose_unit=self.dose_unit,
            severity_level=self.severity_level,
            warning_text=self.warning_text,
        )


class DrugInteractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_a_id: int
    ingredient_b_id: int | None = None
    ingredient_b_external_name: _text(200) | None = None
    interaction_type: InteractionType
    severity_level: SeverityLevel
    handling_type: HandlingType
    min_interval_hours: MinIntervalHours | None = None
    description: _text(4000)
    source: _text(500)
    dose_thresholds: list[DoseThresholdInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _exactly_one_b(self) -> "DrugInteractionCreate":
        _reject_nulls(self, {"min_interval_hours"})
        given = {"ingredient_b_id", "ingredient_b_external_name"} & self.model_fields_set
        if len(given) != 1:
            raise ValueError("exactly one of ingredient_b_id, ingredient_b_external_name")
        return self

    def to_domain(self) -> DrugInteractionContent:
        return DrugInteractionContent(
            ingredient_a_id=self.ingredient_a_id,
            ingredient_b_id=self.ingredient_b_id,
            ingredient_b_external_name=self.ingredient_b_external_name,
            interaction_type=self.interaction_type,
            severity_level=self.severity_level,
            handling_type=self.handling_type,
            min_interval_hours=self.min_interval_hours,
            description=self.description,
            source=self.source,
            dose_thresholds=tuple(t.to_domain() for t in self.dose_thresholds),
        )


class _Update(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _has_change(self) -> "_Update":
        _reject_nulls(self, set(self.NULLABLE))
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("at least one field to change is required")
        return self

    def changes(self) -> dict:
        names = self.model_fields_set - {"expected_version"}
        return {name: getattr(self, name) for name in names}


class DrugInteractionUpdate(_Update):
    interaction_type: InteractionType | None = None
    severity_level: SeverityLevel | None = None
    handling_type: HandlingType | None = None
    min_interval_hours: MinIntervalHours | None = None
    description: _text(4000) | None = None
    source: _text(500) | None = None
    dose_thresholds: list[DoseThresholdInput] | None = Field(default=None, max_length=20)

    NULLABLE: ClassVar[frozenset[str]] = frozenset({"min_interval_hours"})

    def changes(self) -> dict:
        changes = super().changes()
        if "dose_thresholds" in changes:
            changes["dose_thresholds"] = [t.to_domain() for t in changes["dose_thresholds"]]
        return changes


class DrugFoodInteractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: int
    food_to_avoid: _text(200)
    severity_level: SeverityLevel
    reason: _text(4000)
    source: _text(500)

    def to_domain(self) -> DrugFoodInteractionContent:
        return DrugFoodInteractionContent(
            ingredient_id=self.ingredient_id,
            food_to_avoid=self.food_to_avoid,
            severity_level=self.severity_level,
            reason=self.reason,
            source=self.source,
        )


class DrugFoodInteractionUpdate(_Update):
    food_to_avoid: _text(200) | None = None
    severity_level: SeverityLevel | None = None
    reason: _text(4000) | None = None
    source: _text(500) | None = None


# ---------------------------------------------------------------- response


class ActiveIngredientRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    standard_name: str


class AdminRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str | None


class DoseThresholdOut(BaseModel):
    model_config = ConfigDict(extra="forbid", title="DoseThreshold")

    id: int
    ingredient_ref: Literal["A", "B"]
    min_dose: float | None
    max_dose: float | None
    dose_unit: str
    severity_level: int
    warning_text: str


class _VersionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    version: int
    version_id: int
    state: RecordState
    source: str
    verification_status: Literal["da_xac_minh"]
    created_at: datetime
    updated_at: datetime
    updated_by: AdminRef | None
    superseded_at: datetime | None
    deleted_at: datetime | None
    deleted_by: AdminRef | None

    @staticmethod
    def _common(view: RuleView) -> dict:
        meta = view.record.meta

        def admin(user_id: UUID | None) -> AdminRef | None:
            if user_id is None:
                return None
            return AdminRef(id=user_id, email=view.admin_emails.get(user_id))

        return dict(
            id=meta.rule_id,
            version=meta.version,
            version_id=meta.version_id,
            state=meta.state,
            source=view.record.content.source,
            verification_status=VERIFICATION_STATUS,
            created_at=meta.rule_created_at,
            updated_at=meta.created_at,
            updated_by=admin(meta.created_by),
            superseded_at=meta.superseded_at,
            deleted_at=meta.deleted_at,
            deleted_by=admin(meta.deleted_by),
        )


class DrugInteraction(_VersionFields):
    ingredient_a: ActiveIngredientRef
    ingredient_b: ActiveIngredientRef | None
    ingredient_b_external_name: str | None
    interaction_type: InteractionType
    severity_level: int
    handling_type: HandlingType
    min_interval_hours: float | None
    description: str
    dose_thresholds: list[DoseThresholdOut]

    @classmethod
    def from_view(cls, view: RuleView[DrugInteractionContent]) -> "DrugInteraction":
        c = view.record.content

        def ingredient(i: int | None) -> ActiveIngredientRef | None:
            if i is None:
                return None
            return ActiveIngredientRef(id=i, standard_name=view.ingredient_names.get(i, ""))

        return cls(
            **cls._common(view),
            ingredient_a=ingredient(c.ingredient_a_id),
            ingredient_b=ingredient(c.ingredient_b_id),
            ingredient_b_external_name=c.ingredient_b_external_name,
            interaction_type=c.interaction_type,
            severity_level=c.severity_level,
            handling_type=c.handling_type,
            min_interval_hours=c.min_interval_hours,
            description=c.description,
            dose_thresholds=[
                DoseThresholdOut(
                    id=t.id,
                    ingredient_ref=t.ingredient_ref,
                    min_dose=t.min_dose,
                    max_dose=t.max_dose,
                    dose_unit=t.dose_unit,
                    severity_level=t.severity_level,
                    warning_text=t.warning_text,
                )
                for t in c.dose_thresholds
            ],
        )


class DrugFoodInteraction(_VersionFields):
    ingredient: ActiveIngredientRef
    food_to_avoid: str
    severity_level: int
    reason: str

    @classmethod
    def from_view(cls, view: RuleView[DrugFoodInteractionContent]) -> "DrugFoodInteraction":
        c = view.record.content
        return cls(
            **cls._common(view),
            ingredient=ActiveIngredientRef(
                id=c.ingredient_id, standard_name=view.ingredient_names.get(c.ingredient_id, "")
            ),
            food_to_avoid=c.food_to_avoid,
            severity_level=c.severity_level,
            reason=c.reason,
        )


class DrugInteractionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DrugInteraction] = Field(max_length=100)
    total: int = Field(ge=0)


class DrugInteractionVersionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DrugInteraction]


class DrugFoodInteractionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DrugFoodInteraction] = Field(max_length=100)
    total: int = Field(ge=0)


class DrugFoodInteractionVersionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DrugFoodInteraction]


class ErrorDetail(BaseModel):
    detail: str
