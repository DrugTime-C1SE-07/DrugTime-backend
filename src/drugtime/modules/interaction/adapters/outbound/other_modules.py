"""Adapter gọi module khác qua api.py (task 2.16)."""

from uuid import UUID

from drugtime.modules.catalog import api as catalog
from drugtime.modules.identity import api as identity
from drugtime.shared.uow import UnitOfWork


class CatalogIngredients:
    def existing_ids(self, uow: UnitOfWork, ids: list[int]) -> set[int]:
        return catalog.existing_ingredient_ids(uow, ids)

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
        return catalog.ingredient_names(uow, ids)

    def ids_matching(self, uow: UnitOfWork, q: str) -> list[int]:
        return catalog.ingredient_ids_matching(uow, q)

    def ids_of_medication(self, uow: UnitOfWork, medication_id: int) -> list[int]:
        return catalog.ingredient_ids_of_medication(uow, medication_id)


class IdentityAdmins:
    def emails(self, uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
        return identity.user_emails(uow, user_ids)
