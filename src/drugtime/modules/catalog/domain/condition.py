from dataclasses import dataclass
from typing import Literal

ConditionCategory = Literal["chronic_disease", "physiological_state"]

# conditions.medical_nature -> API category. Physiological states (pregnancy, breastfeeding)
# are not chronic diseases and must not be counted as such.
CATEGORY_BY_NATURE: dict[str, ConditionCategory] = {
    "benh_ly": "chronic_disease",
    "sinh_ly_binh_thuong": "physiological_state",
}


@dataclass(frozen=True)
class Condition:
    id: int
    name: str
    category: ConditionCategory
