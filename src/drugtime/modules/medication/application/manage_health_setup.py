from dataclasses import replace
from uuid import UUID

from drugtime.modules.medication.application.profile_ports import (
    ConditionCatalog,
    HealthSetupStore,
    UserConditions,
)
from drugtime.modules.medication.domain.health_setup import (
    MAX_ALLERGY_NAME,
    MAX_CONDITION_NAME,
    HealthSetup,
    SetupStep,
    normalize_custom_names,
)
from drugtime.modules.medication.domain.user_condition import NewUserCondition
from drugtime.shared.errors import Conflict, DomainError
from drugtime.shared.uow import UnitOfWork


def read_setup(
    uow: UnitOfWork, user_id: UUID, store: HealthSetupStore, links: UserConditions
) -> HealthSetup:
    store.lock(uow, user_id)
    return store.read(uow, user_id, links.list(uow, user_id))


def save_setup(
    uow: UnitOfWork,
    user_id: UUID,
    store: HealthSetupStore,
    links: UserConditions,
    catalog: ConditionCatalog,
    revision: str,
    allergies: SetupStep[str] | None,
    conditions: SetupStep[int] | None,
) -> HealthSetup:
    store.lock(uow, user_id)
    existing_links = links.list(uow, user_id)
    current = store.read(uow, user_id, existing_links)
    if revision != current.revision:
        raise Conflict("health_setup_revision_conflict")
    if allergies is not None:
        # An id must be an active catalog entry, unless it is already stored: the app resubmits
        # the stored selection, which may include entries retired since they were chosen.
        stored = set(current.allergies.catalog_ids)
        added = sorted(set(allergies.catalog_ids) - stored)
        if added and set(added) - catalog.active_allergen_ids(uow, added):
            raise DomainError("allergen_not_found")
        allergies = replace(
            allergies,
            catalog_ids=tuple(sorted(allergies.catalog_ids)),
            custom_names=normalize_custom_names(allergies.custom_names, MAX_ALLERGY_NAME),
        )
    if conditions is not None:
        if any(catalog.get_name(uow, item) is None for item in conditions.catalog_ids):
            raise DomainError("condition_not_found")
        conditions = replace(
            conditions,
            catalog_ids=tuple(sorted(conditions.catalog_ids)),
            custom_names=normalize_custom_names(conditions.custom_names, MAX_CONDITION_NAME),
        )
    next_allergies = allergies or current.allergies
    next_conditions = conditions or current.conditions
    if (next_allergies, next_conditions) == (current.allergies, current.conditions):
        return current
    if conditions is not None:
        by_condition = {link.condition_id: link.id for link in existing_links}
        selected = set(conditions.catalog_ids)
        for removed in sorted(by_condition.keys() - selected):
            links.delete(uow, user_id, by_condition[removed])
        for added in sorted(selected - by_condition.keys()):
            links.insert(uow, user_id, NewUserCondition(added))
    next_revision = store.save(uow, user_id, next_allergies, next_conditions)
    return HealthSetup(next_revision, next_allergies, next_conditions)
