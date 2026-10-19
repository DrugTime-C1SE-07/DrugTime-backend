"""SQL của danh mục quy tắc tương tác có phiên bản (task 2.16).

Mỗi dòng là một phiên bản; DB (migration interaction_rule_versions) chặn sửa nội dung phiên bản,
chặn xóa dòng, và gán `rule_id`, `created_at` khi chèn. Khóa quy tắc = khóa dòng phiên bản 1
(luôn tồn tại, không đổi), để các request ghi trên cùng quy tắc chạy lần lượt.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.interaction.application.ports import RuleFilters
from drugtime.modules.interaction.domain.catalog_rules import (
    VERIFICATION_STATUS,
    DoseThreshold,
    DrugFoodInteractionContent,
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    RuleRecord,
    VersionMeta,
)
from drugtime.shared.errors import Conflict
from drugtime.shared.uow import UnitOfWork

_PAIR_INDEXES = {
    "active_ingredient_interactions_pair_uq",
    "active_ingredient_interactions_external_uq",
    "drug_food_interactions_natural_uq",
}
_VERSION_INDEXES = {
    "active_ingredient_interactions_one_open_version_uq",
    "active_ingredient_interactions_rule_version_uq",
    "drug_food_interactions_one_open_version_uq",
    "drug_food_interactions_rule_version_uq",
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _translate(exc: IntegrityError) -> Exception:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint in _PAIR_INDEXES:
        return Conflict("interaction_rule_exists")
    if constraint in _VERSION_INDEXES:  # chỉ xảy ra nếu bỏ qua khóa quy tắc
        return Conflict("version_conflict")
    return exc


def _float(value) -> float | None:
    return None if value is None else float(value)


class _SqlRuleTable:
    table: str
    content_columns: str

    def _meta_select(self) -> str:
        return (
            "t.id, t.rule_id, t.version, t.created_at, t.created_by, t.superseded_at, "
            "t.deleted_at, t.deleted_by, "
            f"(SELECT v1.created_at FROM {self.table} v1 "
            " WHERE v1.rule_id = t.rule_id AND v1.version = 1) AS rule_created_at"
        )

    @staticmethod
    def _meta(r) -> VersionMeta:
        return VersionMeta(
            rule_id=r.rule_id,
            version=r.version,
            version_id=r.id,
            rule_created_at=r.rule_created_at,
            created_at=r.created_at,
            created_by=r.created_by,
            superseded_at=r.superseded_at,
            deleted_at=r.deleted_at,
            deleted_by=r.deleted_by,
        )

    def _records(self, uow: UnitOfWork, rows) -> list[RuleRecord]:
        raise NotImplementedError

    def _select(self, uow: UnitOfWork, where: str, params: dict, tail: str = "") -> list:
        rows = uow.connection.execute(
            text(
                f"SELECT {self._meta_select()}, {self.content_columns} "
                f"FROM {self.table} t WHERE {where} {tail}"
            ),
            params,
        ).all()
        return self._records(uow, rows)

    def lock(self, uow: UnitOfWork, rule_id: int) -> bool:
        row = uow.connection.execute(
            text(f"SELECT 1 FROM {self.table} WHERE rule_id = :r AND version = 1 FOR UPDATE"),
            {"r": rule_id},
        ).first()
        return row is not None

    def current(self, uow: UnitOfWork, rule_id: int) -> RuleRecord | None:
        found = self._select(uow, "t.rule_id = :r AND t.superseded_at IS NULL", {"r": rule_id})
        return found[0] if found else None

    def get_version(self, uow: UnitOfWork, version_id: int) -> RuleRecord | None:
        found = self._select(uow, "t.id = :id", {"id": version_id})
        return found[0] if found else None

    def versions(self, uow: UnitOfWork, rule_id: int) -> list[RuleRecord]:
        return self._select(uow, "t.rule_id = :r", {"r": rule_id}, "ORDER BY t.version DESC")

    def supersede(self, uow: UnitOfWork, version_id: int) -> None:
        uow.connection.execute(
            text(
                f"UPDATE {self.table} SET superseded_at = now() "
                "WHERE id = :id AND superseded_at IS NULL AND deleted_at IS NULL"
            ),
            {"id": version_id},
        )

    def mark_deleted(self, uow: UnitOfWork, version_id: int, deleted_by: UUID) -> None:
        uow.connection.execute(
            text(
                f"UPDATE {self.table} SET deleted_at = now(), deleted_by = :by "
                "WHERE id = :id AND superseded_at IS NULL AND deleted_at IS NULL"
            ),
            {"id": version_id, "by": deleted_by},
        )

    def _filter_clauses(self, filters: RuleFilters) -> tuple[list[str], dict]:
        raise NotImplementedError

    def list_current(
        self, uow: UnitOfWork, filters: RuleFilters, skip: int, limit: int
    ) -> tuple[list[RuleRecord], int]:
        where, params = self._filter_clauses(filters)
        cond = " AND ".join(["t.superseded_at IS NULL", "t.deleted_at IS NULL", *where])
        total = uow.connection.execute(
            text(f"SELECT count(*) FROM {self.table} t WHERE {cond}"), params
        ).scalar_one()
        records = self._select(
            uow,
            cond,
            {**params, "skip": skip, "limit": limit},
            "ORDER BY t.created_at DESC, t.rule_id DESC OFFSET :skip LIMIT :limit",
        )
        return records, int(total)


class SqlDrugInteractions(_SqlRuleTable):
    table = "active_ingredient_interactions"
    content_columns = (
        "t.ingredient_a_id, t.ingredient_b_id, t.ingredient_b_external_name, "
        "t.interaction_type::text AS interaction_type, t.severity_level, "
        "t.handling_type::text AS handling_type, t.min_interval_hours, t.description, t.source"
    )

    def _records(self, uow: UnitOfWork, rows) -> list[RuleRecord[DrugInteractionContent]]:
        thresholds: dict[int, list[DoseThreshold]] = {}
        if rows:
            for t in uow.connection.execute(
                text(
                    "SELECT id, interaction_id, ingredient_ref, min_dose, max_dose, dose_unit, "
                    "severity_level, warning_text "
                    "FROM active_ingredient_interaction_dose_thresholds "
                    "WHERE interaction_id = ANY(:ids) ORDER BY id"
                ),
                {"ids": [r.id for r in rows]},
            ):
                thresholds.setdefault(t.interaction_id, []).append(
                    DoseThreshold(
                        ingredient_ref=t.ingredient_ref,
                        min_dose=_float(t.min_dose),
                        max_dose=_float(t.max_dose),
                        dose_unit=t.dose_unit,
                        severity_level=t.severity_level,
                        warning_text=t.warning_text,
                        id=t.id,
                    )
                )
        return [
            RuleRecord(
                content=DrugInteractionContent(
                    ingredient_a_id=r.ingredient_a_id,
                    ingredient_b_id=r.ingredient_b_id,
                    ingredient_b_external_name=r.ingredient_b_external_name,
                    interaction_type=InteractionType(r.interaction_type),
                    severity_level=r.severity_level,
                    handling_type=HandlingType(r.handling_type),
                    min_interval_hours=_float(r.min_interval_hours),
                    description=r.description,
                    source=r.source,
                    dose_thresholds=tuple(thresholds.get(r.id, ())),
                ),
                meta=self._meta(r),
            )
            for r in rows
        ]

    def insert(
        self,
        uow: UnitOfWork,
        content: DrugInteractionContent,
        *,
        rule_id: int | None,
        version: int,
        created_by: UUID,
    ) -> int:
        c = uow.connection
        try:
            version_id = c.execute(
                text(
                    "INSERT INTO active_ingredient_interactions (rule_id, version, "
                    "ingredient_a_id, ingredient_b_id, ingredient_b_external_name, "
                    "ingredient_b_in_table_a, interaction_type, severity_level, handling_type, "
                    "min_interval_hours, description, source, verification_status, created_by) "
                    "VALUES (:rule_id, :version, :a, :b, :b_ext, CAST(:in_a AS yes_no), "
                    "CAST(:itype AS interaction_type), :sev, CAST(:handling AS handling_type), "
                    ":interval, :description, :source, :verification, :by) RETURNING id"
                ),
                {
                    "rule_id": rule_id,
                    "version": version,
                    "a": content.ingredient_a_id,
                    "b": content.ingredient_b_id,
                    "b_ext": content.ingredient_b_external_name,
                    "in_a": "co" if content.ingredient_b_id is not None else "khong",
                    "itype": content.interaction_type.value,
                    "sev": content.severity_level,
                    "handling": content.handling_type.value,
                    "interval": content.min_interval_hours,
                    "description": content.description,
                    "source": content.source,
                    "verification": VERIFICATION_STATUS,
                    "by": created_by,
                },
            ).scalar_one()
        except IntegrityError as exc:
            raise _translate(exc) from exc
        if content.dose_thresholds:
            c.execute(
                text(
                    "INSERT INTO active_ingredient_interaction_dose_thresholds (interaction_id, "
                    "ingredient_ref, min_dose, max_dose, dose_unit, severity_level, warning_text) "
                    "VALUES (:iid, :ref, :lo, :hi, :unit, :sev, :text)"
                ),
                [
                    {
                        "iid": version_id,
                        "ref": t.ingredient_ref,
                        "lo": t.min_dose,
                        "hi": t.max_dose,
                        "unit": t.dose_unit,
                        "sev": t.severity_level,
                        "text": t.warning_text,
                    }
                    for t in content.dose_thresholds
                ],
            )
        return version_id

    def _filter_clauses(self, f: RuleFilters) -> tuple[list[str], dict]:
        where: list[str] = []
        params: dict = {}
        if f.ingredient_id is not None:
            where.append("(t.ingredient_a_id = :ing OR t.ingredient_b_id = :ing)")
            params["ing"] = f.ingredient_id
        if f.medication_ingredient_ids is not None:
            where.append("(t.ingredient_a_id = ANY(:med) OR t.ingredient_b_id = ANY(:med))")
            params["med"] = f.medication_ingredient_ids
        if f.query_text is not None:
            where.append(
                "(t.ingredient_a_id = ANY(:qids) OR t.ingredient_b_id = ANY(:qids) "
                "OR t.ingredient_b_external_name ILIKE :pattern ESCAPE '\\')"
            )
            params["qids"] = f.query_ingredient_ids or []
            params["pattern"] = f"%{_escape_like(f.query_text)}%"
        if f.interaction_type is not None:
            where.append("t.interaction_type = CAST(:itype AS interaction_type)")
            params["itype"] = f.interaction_type
        if f.severity_level is not None:
            where.append("t.severity_level = :sev")
            params["sev"] = f.severity_level
        return where, params


class SqlDrugFoodInteractions(_SqlRuleTable):
    table = "drug_food_interactions"
    content_columns = (
        "t.active_ingredient_id, t.food_to_avoid, t.severity_level, t.reason, t.source"
    )

    def _records(self, uow: UnitOfWork, rows) -> list[RuleRecord[DrugFoodInteractionContent]]:
        return [
            RuleRecord(
                content=DrugFoodInteractionContent(
                    ingredient_id=r.active_ingredient_id,
                    food_to_avoid=r.food_to_avoid,
                    severity_level=r.severity_level,
                    reason=r.reason,
                    source=r.source,
                ),
                meta=self._meta(r),
            )
            for r in rows
        ]

    def insert(
        self,
        uow: UnitOfWork,
        content: DrugFoodInteractionContent,
        *,
        rule_id: int | None,
        version: int,
        created_by: UUID,
    ) -> int:
        try:
            return uow.connection.execute(
                text(
                    "INSERT INTO drug_food_interactions (rule_id, version, active_ingredient_id, "
                    "food_to_avoid, severity_level, reason, source, verification_status, "
                    "created_by) VALUES (:rule_id, :version, :ing, :food, :sev, :reason, "
                    ":source, :verification, :by) RETURNING id"
                ),
                {
                    "rule_id": rule_id,
                    "version": version,
                    "ing": content.ingredient_id,
                    "food": content.food_to_avoid,
                    "sev": content.severity_level,
                    "reason": content.reason,
                    "source": content.source,
                    "verification": VERIFICATION_STATUS,
                    "by": created_by,
                },
            ).scalar_one()
        except IntegrityError as exc:
            raise _translate(exc) from exc

    def _filter_clauses(self, f: RuleFilters) -> tuple[list[str], dict]:
        where: list[str] = []
        params: dict = {}
        if f.ingredient_id is not None:
            where.append("t.active_ingredient_id = :ing")
            params["ing"] = f.ingredient_id
        if f.medication_ingredient_ids is not None:
            where.append("t.active_ingredient_id = ANY(:med)")
            params["med"] = f.medication_ingredient_ids
        if f.query_text is not None:
            where.append(
                "(t.active_ingredient_id = ANY(:qids) "
                "OR t.food_to_avoid ILIKE :pattern ESCAPE '\\')"
            )
            params["qids"] = f.query_ingredient_ids or []
            params["pattern"] = f"%{_escape_like(f.query_text)}%"
        if f.severity_level is not None:
            where.append("t.severity_level = :sev")
            params["sev"] = f.severity_level
        return where, params
