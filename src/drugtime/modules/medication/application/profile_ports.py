from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.medication.domain.health_setup import AllergenLabel, HealthSetup, SetupStep
from drugtime.modules.medication.domain.user_condition import (
    NewUserCondition,
    PersonalProfile,
    UserConditionRecord,
)
from drugtime.shared.uow import UnitOfWork


class HealthProfileAccess(Protocol):
    def authorize_read(self, uow: UnitOfWork, user_id: UUID, is_admin: bool) -> None: ...
    def authorize_write(self, uow: UnitOfWork, user_id: UUID, is_admin: bool) -> None: ...


class PersonalProfiles(Protocol):
    def get(self, uow: UnitOfWork, user_id: UUID) -> PersonalProfile: ...
    def update(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        *,
        full_name: str,
        date_of_birth: date,
        gender: str,
        email: str | None,
        phone_number: str | None,
        at: datetime,
    ) -> tuple[str | None, bool]: ...


class ConditionCatalog(Protocol):
    def get_name(self, uow: UnitOfWork, condition_id: int) -> str | None: ...
    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]: ...
    def active_allergen_ids(self, uow: UnitOfWork, ids: list[str]) -> set[str]: ...
    def allergen_labels(self, uow: UnitOfWork, ids: list[str]) -> dict[str, AllergenLabel]: ...


class UserConditions(Protocol):
    def list(self, uow: UnitOfWork, user_id: UUID) -> list[UserConditionRecord]: ...
    def insert(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        cmd: NewUserCondition,
    ) -> UserConditionRecord | None: ...
    def update(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        link_id: int,
        fields: dict[str, str | None],
    ) -> UserConditionRecord | None: ...
    def delete(self, uow: UnitOfWork, user_id: UUID, link_id: int) -> bool: ...


class HealthSetupStore(Protocol):
    def lock(self, uow: UnitOfWork, user_id: UUID) -> None: ...
    def read(
        self, uow: UnitOfWork, user_id: UUID, links: list[UserConditionRecord]
    ) -> HealthSetup: ...
    def save(
        self, uow: UnitOfWork, user_id: UUID, allergies: SetupStep[str], conditions: SetupStep[int]
    ) -> str: ...
    def touch_condition_links(self, uow: UnitOfWork, user_id: UUID) -> None: ...
