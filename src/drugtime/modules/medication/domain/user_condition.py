from dataclasses import dataclass
from datetime import date
from typing import Literal

ConditionCategory = Literal["chronic_disease", "physiological_state"]


@dataclass(frozen=True)
class ConditionLabel:
    """Catalog name and category of a condition id."""

    name: str
    category: ConditionCategory


@dataclass(frozen=True)
class UserConditionRecord:
    id: int
    condition_id: int
    subtype: str | None
    stage: str | None


@dataclass(frozen=True)
class UserConditionView:
    id: int
    condition_id: int
    condition_name: str
    subtype: str | None
    stage: str | None
    category: ConditionCategory = "chronic_disease"


@dataclass(frozen=True)
class NewUserCondition:
    condition_id: int
    subtype: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class PersonalProfile:
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    email: str | None
    phone_number: str | None = None


@dataclass(frozen=True)
class HealthProfile:
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    email: str | None
    conditions: list[UserConditionView]
    phone_number: str | None = None
