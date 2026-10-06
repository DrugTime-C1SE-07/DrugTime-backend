"""Request/response của /medications, khớp api_contract/openapi.json (task 2.01).

Field không cho phép `null` khai báo kiểu không có None nhưng mặc định None: Pydantic không
kiểm giá trị mặc định, nên "không gửi" được chấp nhận còn "gửi null" bị 422.
"""

from datetime import datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from drugtime.modules.medication.domain.user_medication import (
    DosingMode,
    IntakeTiming,
    MedicationChanges,
    NewMedication,
    UserMedicationView,
)
from drugtime.shared.config import get_settings

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

IntakeTime = Annotated[str, Field(pattern=TIME_PATTERN, examples=["08:00"])]
IntakeTimes = Annotated[list[IntakeTime], Field(min_length=1, max_length=6)]
DayOfWeek = Annotated[int, Field(ge=1, le=7)]
DaysOfWeek = Annotated[list[DayOfWeek], Field(min_length=1, max_length=7)]
QuantityPerDose = Annotated[float, Field(gt=0, le=10)]
MaxDosesPerDay = Annotated[int, Field(ge=1, le=6)]
StockQuantity = Annotated[int | None, Field(ge=0, le=9999)]


def _unique(values: list | None) -> list | None:
    if values is not None and len(set(values)) != len(values):
        raise ValueError("items must be unique")
    return values


def _to_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _quantity(value: float) -> Decimal:
    return Decimal(str(value))


class UserMedicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: Annotated[str, Field(pattern=UUID_PATTERN, json_schema_extra={"format": "uuid"})]
    medication_id: Annotated[int, Field(ge=1)]
    quantity_per_dose: QuantityPerDose
    dosing_mode: DosingMode
    intake_times: IntakeTimes = None
    days_of_week: DaysOfWeek = None
    max_doses_per_day: MaxDosesPerDay = None
    intake_timing: IntakeTiming | None = None
    stock_quantity: StockQuantity = None

    @field_validator("intake_times", "days_of_week")
    @classmethod
    def _no_duplicates(cls, v: list | None) -> list | None:
        return _unique(v)

    def to_domain(self) -> NewMedication:
        return NewMedication(
            client_uuid=UUID(self.client_uuid),
            medication_id=self.medication_id,
            quantity_per_dose=_quantity(self.quantity_per_dose),
            dosing_mode=self.dosing_mode,
            intake_times=None
            if self.intake_times is None
            else tuple(_to_time(t) for t in self.intake_times),
            days_of_week=None if self.days_of_week is None else tuple(self.days_of_week),
            max_doses_per_day=self.max_doses_per_day,
            intake_timing=self.intake_timing,
            stock_quantity=self.stock_quantity,
        )


class UserMedicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"minProperties": 1})

    quantity_per_dose: QuantityPerDose = None
    dosing_mode: DosingMode = None
    intake_times: IntakeTimes = None
    max_doses_per_day: MaxDosesPerDay = None
    intake_timing: IntakeTiming | None = None
    stock_quantity: StockQuantity = None
    stopped: StrictBool = None  # "false" dạng chuỗi bị 422, như contract (boolean)

    @field_validator("intake_times")
    @classmethod
    def _no_duplicates(cls, v: list | None) -> list | None:
        return _unique(v)

    @model_validator(mode="after")
    def _not_empty(self) -> "UserMedicationUpdate":
        if not self.model_fields_set:
            raise ValueError("body must contain at least one field")
        return self

    def to_domain(self) -> MedicationChanges:
        return MedicationChanges(
            sent=frozenset(self.model_fields_set),
            quantity_per_dose=None
            if self.quantity_per_dose is None
            else _quantity(self.quantity_per_dose),
            dosing_mode=self.dosing_mode,
            intake_times=None
            if self.intake_times is None
            else tuple(_to_time(t) for t in self.intake_times),
            max_doses_per_day=self.max_doses_per_day,
            intake_timing=self.intake_timing,
            stock_quantity=self.stock_quantity,
            stopped=bool(self.stopped),
        )


class CatalogMedicationSummary(BaseModel):
    id: int
    name: str
    active_ingredient: str | None
    strength_text: str | None
    dosage_form: str | None


class MedicationSchedule(BaseModel):
    id: int
    intake_time: IntakeTime
    days_of_week: list[DayOfWeek]
    reminder_enabled: bool
    effective_from: datetime


class UserMedication(BaseModel):
    id: int
    medication: CatalogMedicationSummary
    dosing_mode: DosingMode
    quantity_per_dose: float
    doses_per_day: int
    intake_timing: IntakeTiming | None
    stock_quantity: int | None
    has_interaction_data: bool
    status: Literal["active", "stopped"]
    ended_at: datetime | None
    schedules: list[MedicationSchedule]

    @classmethod
    def from_view(cls, view: UserMedicationView) -> "UserMedication":
        tz = ZoneInfo(get_settings().timezone)
        r, m = view.record, view.medication
        return cls(
            id=r.id,
            medication=CatalogMedicationSummary(
                id=m.id,
                name=m.name,
                active_ingredient=m.active_ingredient,
                strength_text=m.strength_text,
                dosage_form=m.dosage_form,
            ),
            dosing_mode=r.dosing_mode,
            quantity_per_dose=float(r.quantity_per_dose),
            doses_per_day=r.doses_per_day,
            intake_timing=r.intake_timing,
            stock_quantity=r.stock_quantity,
            has_interaction_data=r.has_interaction_data,
            status="active" if r.ended_at is None else "stopped",
            ended_at=None if r.ended_at is None else r.ended_at.astimezone(tz),
            schedules=[
                MedicationSchedule(
                    id=s.id,
                    intake_time=s.intake_time.strftime("%H:%M"),
                    days_of_week=list(s.days_of_week),
                    reminder_enabled=s.reminder_enabled,
                    effective_from=s.effective_from.astimezone(tz),
                )
                for s in r.schedules
            ],
        )


class UserMedicationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserMedication]
