"""InteractionEvaluator: hàm thuần, tất định (CD7). Không đọc DB, không gọi LLM."""

from enum import StrEnum


class CheckResult(StrEnum):
    FOUND = "co_tuong_tac"
    NONE_FOUND = "da_kiem_tra_khong_thay"
    INSUFFICIENT_DATA = "khong_du_du_lieu"


# TODO: evaluate(medications, rules) -> findings (3 trạng thái, tách thuốc chưa map hoạt chất)
