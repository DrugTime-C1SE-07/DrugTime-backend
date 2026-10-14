from datetime import date, datetime
from typing import Protocol
from uuid import UUID

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
        at: datetime,
    ) -> None: ...


class ConditionCatalog(Protocol):
    def get_name(self, uow: UnitOfWork, condition_id: int) -> str | None: ...
    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]: ...


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
