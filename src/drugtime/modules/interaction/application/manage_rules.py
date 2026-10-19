"""Use case chung cho quy tắc tương tác có phiên bản (task 2.16).

Thứ tự kiểm theo contract:
- tạo: hoạt chất tồn tại (422) → quy tắc nghiệp vụ (422) → trùng cặp (409, do store);
- sửa: quy tắc tồn tại và chưa xóa (404) → `expected_version` (409) → nghiệp vụ trên nội dung
  sau khi gộp (422) → giống hệt thì không ghi → đóng phiên bản cũ, chèn phiên bản mới;
- xóa: 404 → 409 → đánh dấu xóa mềm phiên bản hiện hành.
Danh mục quy tắc không phải dữ liệu sức khỏe: không qua PEP, không ghi nhật ký truy cập.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from drugtime.modules.interaction.application.ports import (
    AdminDirectory,
    IngredientCatalog,
    RuleFilters,
    RuleStore,
)
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    DrugInteractionContent,
    RuleRecord,
    merge,
    same_content,
)
from drugtime.shared.errors import Conflict, DomainError, NotFound
from drugtime.shared.uow import UnitOfWork

RULE_NOT_FOUND = "interaction_rule_not_found"
VERSION_NOT_FOUND = "interaction_version_not_found"


@dataclass(frozen=True)
class ListQuery:
    q: str | None = None
    ingredient_id: int | None = None
    medication_id: int | None = None
    interaction_type: str | None = None
    severity_level: int | None = None
    skip: int = 0
    limit: int = 20


@dataclass(frozen=True)
class RuleView[C: (DrugInteractionContent, DrugFoodInteractionContent)]:
    """Phiên bản kèm thông tin hiển thị: tên chuẩn hoạt chất và email admin."""

    record: RuleRecord[C]
    ingredient_names: dict[int, str]
    admin_emails: dict[UUID, str | None]


class RuleService[C: (DrugInteractionContent, DrugFoodInteractionContent)]:
    def __init__(
        self,
        store: RuleStore[C],
        ingredients: IngredientCatalog,
        admins: AdminDirectory,
        validate: Callable[[C], None],
    ) -> None:
        self.store = store
        self.ingredients = ingredients
        self.admins = admins
        self.validate = validate

    # ---------------------------------------------------------------- đọc
    def _views(self, uow: UnitOfWork, records: list[RuleRecord[C]]) -> list[RuleView[C]]:
        ingredient_ids = sorted({i for r in records for i in r.content.ingredient_ids()})
        admin_ids = sorted(
            {a for r in records for a in (r.meta.created_by, r.meta.deleted_by) if a is not None},
            key=str,
        )
        names = self.ingredients.names(uow, ingredient_ids)
        emails = self.admins.emails(uow, admin_ids)
        return [RuleView(r, names, emails) for r in records]

    def _current_or_404(self, uow: UnitOfWork, rule_id: int) -> RuleRecord[C]:
        current = self.store.current(uow, rule_id)
        if current is None or current.meta.deleted_at is not None:
            raise NotFound(RULE_NOT_FOUND)
        return current

    def get(self, uow: UnitOfWork, rule_id: int) -> RuleView[C]:
        return self._views(uow, [self._current_or_404(uow, rule_id)])[0]

    def get_version(self, uow: UnitOfWork, version_id: int) -> RuleView[C]:
        record = self.store.get_version(uow, version_id)
        if record is None:
            raise NotFound(VERSION_NOT_FOUND)
        return self._views(uow, [record])[0]

    def history(self, uow: UnitOfWork, rule_id: int) -> list[RuleView[C]]:
        records = self.store.versions(uow, rule_id)
        if not records:
            raise NotFound(RULE_NOT_FOUND)
        return self._views(uow, records)

    def list(self, uow: UnitOfWork, query: ListQuery) -> tuple[list[RuleView[C]], int]:
        medication_ids = None
        if query.medication_id is not None:
            medication_ids = self.ingredients.ids_of_medication(uow, query.medication_id)
            if not medication_ids:
                return [], 0
        text = query.q.strip() if query.q is not None and query.q.strip() else None
        filters = RuleFilters(
            ingredient_id=query.ingredient_id,
            medication_ingredient_ids=medication_ids,
            query_text=text,
            query_ingredient_ids=self.ingredients.ids_matching(uow, text) if text else None,
            interaction_type=query.interaction_type,
            severity_level=query.severity_level,
        )
        records, total = self.store.list_current(uow, filters, query.skip, query.limit)
        return self._views(uow, records), total

    # ---------------------------------------------------------------- ghi
    def create(self, uow: UnitOfWork, admin_id: UUID, content: C) -> RuleView[C]:
        ids = content.ingredient_ids()
        if set(ids) - self.ingredients.existing_ids(uow, ids):
            raise DomainError("active_ingredient_not_found")
        self.validate(content)
        version_id = self.store.insert(uow, content, rule_id=None, version=1, created_by=admin_id)
        return self.get_version(uow, version_id)

    def _locked_current(self, uow: UnitOfWork, rule_id: int, expected: int) -> RuleRecord[C]:
        if not self.store.lock(uow, rule_id):
            raise NotFound(RULE_NOT_FOUND)
        current = self._current_or_404(uow, rule_id)
        if current.meta.version != expected:
            raise Conflict("version_conflict")
        return current

    def update(
        self, uow: UnitOfWork, admin_id: UUID, rule_id: int, expected_version: int, changes: dict
    ) -> RuleView[C]:
        current = self._locked_current(uow, rule_id, expected_version)
        updated = merge(current.content, changes)
        self.validate(updated)
        if same_content(current.content, updated):
            return self._views(uow, [current])[0]
        self.store.supersede(uow, current.meta.version_id)
        version_id = self.store.insert(
            uow, updated, rule_id=rule_id, version=current.meta.version + 1, created_by=admin_id
        )
        return self.get_version(uow, version_id)

    def delete(self, uow: UnitOfWork, admin_id: UUID, rule_id: int, expected_version: int) -> None:
        current = self._locked_current(uow, rule_id, expected_version)
        self.store.mark_deleted(uow, current.meta.version_id, admin_id)
