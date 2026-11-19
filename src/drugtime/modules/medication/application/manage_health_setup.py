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
from drugtime.modules.medication.domain.user_condition import (
    ConditionCategory,
    NewUserCondition,
    UserConditionRecord,
)
from drugtime.shared.errors import Conflict, DomainError
from drugtime.shared.uow import UnitOfWork


def _categories(
    uow: UnitOfWork, catalog: ConditionCatalog, links: list[UserConditionRecord]
) -> dict[int, ConditionCategory]:
    ids = sorted({link.condition_id for link in links})
    return {i: label.category for i, label in catalog.labels(uow, ids).items()}


def read_setup(
    uow: UnitOfWork,
    user_id: UUID,
    store: HealthSetupStore,
    links: UserConditions,
    catalog: ConditionCatalog,
) -> HealthSetup:
    store.lock(uow, user_id)
    existing = links.list(uow, user_id)
    return store.read(uow, user_id, existing, _categories(uow, catalog, existing))


def _check_catalog_ids(
    uow: UnitOfWork,
    catalog: ConditionCatalog,
    ids: tuple[int, ...],
    expected: ConditionCategory,
) -> None:
    labels = catalog.labels(uow, sorted(set(ids)))
    if any(item not in labels for item in ids):
        raise DomainError("condition_not_found")
    # A pregnancy id in the chronic-disease step (or the reverse) is rejected before any write.
    if any(labels[item].category != expected for item in ids):
        raise DomainError("condition_category_mismatch")


def _sync_links(
    uow: UnitOfWork,
    user_id: UUID,
    links: UserConditions,
    existing: list[UserConditionRecord],
    categories: dict[int, ConditionCategory],
    category: ConditionCategory,
    selected: tuple[int, ...],
) -> None:
    """Replace the links of one category only; the other category's links are untouched."""
    by_condition = {
        link.condition_id: link.id
        for link in existing
        if categories.get(link.condition_id, "chronic_disease") == category
    }
    for removed in sorted(by_condition.keys() - set(selected)):
        links.delete(uow, user_id, by_condition[removed])
    for added in sorted(set(selected) - by_condition.keys()):
        links.insert(uow, user_id, NewUserCondition(added))


def save_setup(
    uow: UnitOfWork,
    user_id: UUID,
    store: HealthSetupStore,
    links: UserConditions,
    catalog: ConditionCatalog,
    revision: str,
    allergies: SetupStep[str] | None,
    conditions: SetupStep[int] | None,
    physiological_states: SetupStep[int] | None = None,
) -> HealthSetup:
    store.lock(uow, user_id)
    existing_links = links.list(uow, user_id)
    categories = _categories(uow, catalog, existing_links)
    current = store.read(uow, user_id, existing_links, categories)
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
        _check_catalog_ids(uow, catalog, conditions.catalog_ids, "chronic_disease")
        conditions = replace(
            conditions,
            catalog_ids=tuple(sorted(conditions.catalog_ids)),
            custom_names=normalize_custom_names(conditions.custom_names, MAX_CONDITION_NAME),
        )
    if physiological_states is not None:
        if physiological_states.custom_names:
            raise DomainError("invalid_custom_name")
        _check_catalog_ids(uow, catalog, physiological_states.catalog_ids, "physiological_state")
        physiological_states = replace(
            physiological_states, catalog_ids=tuple(sorted(physiological_states.catalog_ids))
        )
    next_allergies = allergies or current.allergies
    next_conditions = conditions or current.conditions
    next_physiological = physiological_states or current.physiological_states
    if (next_allergies, next_conditions, next_physiological) == (
        current.allergies,
        current.conditions,
        current.physiological_states,
    ):
        return current
    if conditions is not None:
        _sync_links(
            uow,
            user_id,
            links,
            existing_links,
            categories,
            "chronic_disease",
            conditions.catalog_ids,
        )
    if physiological_states is not None:
        _sync_links(
            uow,
            user_id,
            links,
            existing_links,
            categories,
            "physiological_state",
            physiological_states.catalog_ids,
        )
    next_revision = store.save(uow, user_id, next_allergies, next_conditions, next_physiological)
    return HealthSetup(next_revision, next_allergies, next_conditions, next_physiological)
