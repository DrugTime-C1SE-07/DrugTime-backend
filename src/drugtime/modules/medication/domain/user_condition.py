from dataclasses import dataclass
from datetime import date


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


@dataclass(frozen=True)
class HealthProfile:
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    conditions: list[UserConditionView]
