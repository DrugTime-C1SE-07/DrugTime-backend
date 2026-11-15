from uuid import UUID

from drugtime.modules.medication.application.profile_ports import (
    ConditionCatalog,
    HealthProfileAccess,
    HealthSetupStore,
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
    setup: HealthSetupStore | None = None,
) -> UserConditionView:
    access.authorize_write(uow, user_id, is_admin)
    if catalog.get_name(uow, cmd.condition_id) is None:
        raise DomainError("condition_not_found")
    if setup is not None:
        setup.lock(uow, user_id)
    link = conditions.insert(uow, user_id, cmd)
    if link is None:
        raise Conflict("condition_already_exists")
    if setup is not None:
        setup.touch_condition_links(uow, user_id)
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
    setup: HealthSetupStore | None = None,
) -> UserConditionView:
    access.authorize_write(uow, user_id, is_admin)
    if not fields:
        raise DomainError("empty_condition_update")
    if not fields.keys() <= {"subtype", "stage"}:
        raise DomainError("invalid_condition_update")
    if setup is not None:
        setup.lock(uow, user_id)
    link = conditions.update(uow, user_id, link_id, fields)
    if link is None:
        raise NotFound("user_condition_not_found")
    if setup is not None:
        setup.touch_condition_links(uow, user_id)
    return _view(uow, catalog, link)


def delete_condition(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    conditions: UserConditions,
    link_id: int,
    setup: HealthSetupStore | None = None,
) -> None:
    access.authorize_write(uow, user_id, is_admin)
    if setup is not None:
        setup.lock(uow, user_id)
    if not conditions.delete(uow, user_id, link_id):
        raise NotFound("user_condition_not_found")
    if setup is not None:
        setup.touch_condition_links(uow, user_id)
