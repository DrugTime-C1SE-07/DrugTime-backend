from uuid import UUID

from drugtime.modules.medication.application.profile_ports import (
    ConditionCatalog,
    HealthProfileAccess,
    UserConditions,
)
from drugtime.modules.medication.domain.user_condition import (
    NewUserCondition,
    UserConditionRecord,
    UserConditionView,
)
from drugtime.shared.errors import Conflict, DomainError, NotFound
from drugtime.shared.uow import UnitOfWork


def _view(
    uow: UnitOfWork, catalog: ConditionCatalog, link: UserConditionRecord
) -> UserConditionView:
    name = catalog.get_name(uow, link.condition_id)
    if name is None:
        raise RuntimeError("Linked condition is missing")
    return UserConditionView(link.id, link.condition_id, name, link.subtype, link.stage)


def create_condition(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    conditions: UserConditions,
    catalog: ConditionCatalog,
    cmd: NewUserCondition,
) -> UserConditionView:
    access.authorize_write(uow, user_id, is_admin)
    if catalog.get_name(uow, cmd.condition_id) is None:
        raise DomainError("condition_not_found")
    link = conditions.insert(uow, user_id, cmd)
    if link is None:
        raise Conflict("condition_already_exists")
    return _view(uow, catalog, link)


def update_condition(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    conditions: UserConditions,
    catalog: ConditionCatalog,
    link_id: int,
    fields: dict[str, str | None],
) -> UserConditionView:
    access.authorize_write(uow, user_id, is_admin)
    if not fields:
        raise DomainError("empty_condition_update")
    if not fields.keys() <= {"subtype", "stage"}:
        raise DomainError("invalid_condition_update")
    link = conditions.update(uow, user_id, link_id, fields)
    if link is None:
        raise NotFound("user_condition_not_found")
    return _view(uow, catalog, link)


def delete_condition(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    conditions: UserConditions,
    link_id: int,
) -> None:
    access.authorize_write(uow, user_id, is_admin)
    if not conditions.delete(uow, user_id, link_id):
        raise NotFound("user_condition_not_found")
