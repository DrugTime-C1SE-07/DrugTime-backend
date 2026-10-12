"""Danh mục quy tắc tương tác có phiên bản (task 2.16). Hàm thuần, không I/O.

Mỗi quy tắc có mã ổn định (`rule_id`); mỗi lần sửa có thay đổi tạo một phiên bản mới, phiên bản
cũ không bao giờ đổi nội dung. Kiểm tra nghiệp vụ chạy trên nội dung sau khi gộp thay đổi, nên bắt
được cả lỗi do sửa một phần (ví dụ đổi sang chống chỉ định trong khi còn ngưỡng liều).
"""

from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from drugtime.shared.errors import DomainError


class InteractionType(StrEnum):
    CONTRAINDICATED = "chong_chi_dinh"
    DOSE_DEPENDENT = "phu_thuoc_lieu"


class HandlingType(StrEnum):
    AVOID = "tranh_phoi_hop"
    MONITOR = "can_theo_doi"
    SPACING = "cach_gio"
    REDUCE_DOSE = "giam_lieu"


class RecordState(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


VERIFICATION_STATUS = "da_xac_minh"  # không có bước duyệt (requirement Q3)
CONTRAINDICATION_SEVERITY = 4


@dataclass(frozen=True)
class DoseThreshold:
    ingredient_ref: str  # "A" | "B"
    min_dose: float | None
    max_dose: float | None
    dose_unit: str
    severity_level: int
    warning_text: str
    id: int | None = field(default=None, compare=False)

    def sort_key(self) -> tuple:
        return (
            self.ingredient_ref,
            self.min_dose is None,
            self.min_dose or 0,
            self.max_dose is None,
            self.max_dose or 0,
            self.dose_unit,
            self.severity_level,
            self.warning_text,
        )


@dataclass(frozen=True)
class DrugInteractionContent:
    ingredient_a_id: int
    ingredient_b_id: int | None
    ingredient_b_external_name: str | None
    interaction_type: InteractionType
    severity_level: int
    handling_type: HandlingType
    min_interval_hours: float | None
    description: str
    source: str
    dose_thresholds: tuple[DoseThreshold, ...] = ()

    def ingredient_ids(self) -> list[int]:
        return [i for i in (self.ingredient_a_id, self.ingredient_b_id) if i is not None]


@dataclass(frozen=True)
class DrugFoodInteractionContent:
    ingredient_id: int
    food_to_avoid: str
    severity_level: int
    reason: str
    source: str

    def ingredient_ids(self) -> list[int]:
        return [self.ingredient_id]


# Field sửa được bằng PATCH; cặp hoạt chất không đổi được (requirement Q4).
DRUG_INTERACTION_EDITABLE = frozenset(
    {
        "interaction_type",
        "severity_level",
        "handling_type",
        "min_interval_hours",
        "description",
        "source",
        "dose_thresholds",
    }
)
DRUG_FOOD_INTERACTION_EDITABLE = frozenset({"food_to_avoid", "severity_level", "reason", "source"})


@dataclass(frozen=True)
class VersionMeta:
    rule_id: int
    version: int
    version_id: int
    rule_created_at: datetime  # thời điểm tạo phiên bản 1
    created_at: datetime  # thời điểm tạo phiên bản này
    created_by: UUID | None
    superseded_at: datetime | None
    deleted_at: datetime | None
    deleted_by: UUID | None

    @property
    def state(self) -> RecordState:
        if self.superseded_at is not None:
            return RecordState.SUPERSEDED
        if self.deleted_at is not None:
            return RecordState.DELETED
        return RecordState.CURRENT


type RuleContent = DrugInteractionContent | DrugFoodInteractionContent


@dataclass(frozen=True)
class RuleRecord[C: (DrugInteractionContent, DrugFoodInteractionContent)]:
    content: C
    meta: VersionMeta


def validate_drug_interaction(c: DrugInteractionContent) -> None:
    """Ném DomainError với mã đầu tiên vi phạm, theo thứ tự trong contract."""
    if c.ingredient_b_id is not None and c.ingredient_b_id == c.ingredient_a_id:
        raise DomainError("same_ingredient")
    contraindicated = c.interaction_type == InteractionType.CONTRAINDICATED
    if contraindicated and c.severity_level != CONTRAINDICATION_SEVERITY:
        raise DomainError("contraindication_severity_mismatch")
    if contraindicated and c.dose_thresholds:
        raise DomainError("threshold_not_allowed")
    for t in c.dose_thresholds:
        if t.ingredient_ref == "B" and c.ingredient_b_id is None:
            raise DomainError("threshold_ref_invalid")
    for t in c.dose_thresholds:
        if t.min_dose is None and t.max_dose is None:
            raise DomainError("threshold_range_invalid")
        if t.min_dose is not None and t.max_dose is not None and t.min_dose > t.max_dose:
            raise DomainError("threshold_range_invalid")
    if c.min_interval_hours is not None and c.handling_type != HandlingType.SPACING:
        raise DomainError("min_interval_not_allowed")


def validate_drug_food_interaction(c: DrugFoodInteractionContent) -> None:
    """Không có quy tắc nghiệp vụ ngoài ràng buộc field và hoạt chất tồn tại."""


def merge[C: (DrugInteractionContent, DrugFoodInteractionContent)](current: C, changes: dict) -> C:
    """Nội dung sau khi áp `changes` (chỉ field sửa được); field không gửi giữ nguyên."""
    allowed = {f.name for f in fields(current)}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    if "dose_thresholds" in changes:
        changes = {**changes, "dose_thresholds": tuple(changes["dose_thresholds"])}
    return replace(current, **changes)


def same_content(a: RuleContent, b: RuleContent) -> bool:
    """So nội dung; ngưỡng liều so như tập (không phụ thuộc thứ tự, bỏ qua id)."""
    if isinstance(a, DrugInteractionContent) and isinstance(b, DrugInteractionContent):
        a = replace(a, dose_thresholds=tuple(sorted(a.dose_thresholds, key=DoseThreshold.sort_key)))
        b = replace(b, dose_thresholds=tuple(sorted(b.dose_thresholds, key=DoseThreshold.sort_key)))
    return a == b
