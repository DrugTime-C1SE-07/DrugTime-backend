from uuid import UUID

from sqlalchemy import text

from drugtime.modules.medication.domain.health_setup import HealthSetup, SetupStep
from drugtime.modules.medication.domain.user_condition import UserConditionRecord
from drugtime.shared.errors import Forbidden
from drugtime.shared.uow import UnitOfWork


class SqlHealthSetup:
    def lock(self, uow: UnitOfWork, user_id: UUID) -> None:
        active = uow.connection.execute(
            text("SELECT erased_at IS NULL FROM users WHERE id = :id FOR NO KEY UPDATE"),
            {"id": user_id},
        ).scalar_one_or_none()
        if not active:
            raise Forbidden("khong_co_quyen")

    def read(self, uow: UnitOfWork, user_id: UUID, links: list[UserConditionRecord]) -> HealthSetup:
        row = (
            uow.connection.execute(
                text(
                    "SELECT revision, allergies_none_known, conditions_none_known, allergen_ids, "
                    "custom_allergies, custom_conditions "
                    "FROM health_profile_setup WHERE user_id = :id"
                ),
                {"id": user_id},
            )
            .mappings()
            .first()
        )
        condition_ids = [link.condition_id for link in links]
        if row is None:
            return HealthSetup(
                "0", SetupStep("unreported"), SetupStep.from_values(False, condition_ids, ())
            )
        return HealthSetup(
            str(row["revision"]),
            SetupStep.from_values(
                row["allergies_none_known"], row["allergen_ids"], row["custom_allergies"]
            ),
            SetupStep.from_values(
                row["conditions_none_known"] and not condition_ids,
                condition_ids,
                row["custom_conditions"],
            ),
        )

    def save(
        self, uow: UnitOfWork, user_id: UUID, allergies: SetupStep[str], conditions: SetupStep[int]
    ) -> str:
        revision = uow.connection.execute(
            text("""
                INSERT INTO health_profile_setup (
                    user_id, revision, allergies_none_known, conditions_none_known,
                    allergen_ids, custom_allergies, custom_conditions
                ) VALUES (
                    :id, 1, :allergies_none, :conditions_none, :allergens, :custom_a, :custom_c
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    revision = health_profile_setup.revision + 1,
                    allergies_none_known = EXCLUDED.allergies_none_known,
                    conditions_none_known = EXCLUDED.conditions_none_known,
                    allergen_ids = EXCLUDED.allergen_ids,
                    custom_allergies = EXCLUDED.custom_allergies,
                    custom_conditions = EXCLUDED.custom_conditions
                RETURNING revision
            """),
            {
                "id": user_id,
                "allergies_none": allergies.status == "none_known",
                "conditions_none": conditions.status == "none_known",
                "allergens": list(allergies.catalog_ids),
                "custom_a": list(allergies.custom_names),
                "custom_c": list(conditions.custom_names),
            },
        ).scalar_one()
        return str(revision)

    def touch_condition_links(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("""
                INSERT INTO health_profile_setup (user_id, revision) VALUES (:id, 1)
                ON CONFLICT (user_id) DO UPDATE SET
                    revision = health_profile_setup.revision + 1,
                    conditions_none_known = false
            """),
            {"id": user_id},
        )
