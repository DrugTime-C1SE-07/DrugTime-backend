"""Port của danh mục quy tắc tương tác (task 2.16). Use case chỉ phụ thuộc các Protocol này."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from drugtime.modules.interaction.domain.catalog_rules import RuleRecord
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class RuleFilters:
    """Bộ lọc danh sách, kết hợp bằng AND. `None` là không lọc."""

    ingredient_id: int | None = None
    # Hoạt chất của một thuốc (lọc `medication_id`): quy tắc chạm bất kỳ hoạt chất nào.
    medication_ingredient_ids: list[int] | None = None
    # Từ khóa (đã bỏ khoảng trắng hai đầu): khớp id hoạt chất có tên khớp, hoặc khớp một phần
    # tên ngoài danh mục / thực phẩm (adapter escape wildcard, không phân biệt hoa thường).
    query_text: str | None = None
    query_ingredient_ids: list[int] | None = None
    interaction_type: str | None = None
    severity_level: int | None = None


class RuleStore[C](Protocol):
    def insert(
        self, uow: UnitOfWork, content: C, *, rule_id: int | None, version: int, created_by: UUID
    ) -> int:
        """Chèn một phiên bản mở (kèm ngưỡng liều nếu có), trả id phiên bản.
        Trùng cặp tự nhiên → Conflict("interaction_rule_exists")."""
        ...

    def lock(self, uow: UnitOfWork, rule_id: int) -> bool:
        """Khóa quy tắc tới hết giao dịch; False nếu chưa từng có quy tắc này."""
        ...

    def current(self, uow: UnitOfWork, rule_id: int) -> RuleRecord[C] | None:
        """Phiên bản chưa bị thay (hiện hành, có thể đã xóa mềm)."""
        ...

    def supersede(self, uow: UnitOfWork, version_id: int) -> None: ...

    def mark_deleted(self, uow: UnitOfWork, version_id: int, deleted_by: UUID) -> None: ...

    def get_version(self, uow: UnitOfWork, version_id: int) -> RuleRecord[C] | None: ...

    def versions(self, uow: UnitOfWork, rule_id: int) -> list[RuleRecord[C]]:
        """Mọi phiên bản, mới nhất trước."""
        ...

    def list_current(
        self, uow: UnitOfWork, filters: RuleFilters, skip: int, limit: int
    ) -> tuple[list[RuleRecord[C]], int]:
        """Phiên bản hiện hành chưa xóa, sắp mới sửa trước; kèm tổng số khớp lọc."""
        ...


class IngredientCatalog(Protocol):
    def existing_ids(self, uow: UnitOfWork, ids: list[int]) -> set[int]: ...

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]: ...

    def ids_matching(self, uow: UnitOfWork, q: str) -> list[int]: ...

    def ids_of_medication(self, uow: UnitOfWork, medication_id: int) -> list[int]: ...


class AdminDirectory(Protocol):
    def emails(self, uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]: ...
