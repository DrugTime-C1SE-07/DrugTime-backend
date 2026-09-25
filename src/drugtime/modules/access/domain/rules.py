"""Quy tắc phân quyền (schema v9, mục "Quy tắc phân quyền"). Hàm thuần, không I/O."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Scope(StrEnum):
    HEALTH_PROFILE = "ho_so_suc_khoe"
    MEDICATIONS = "danh_sach_thuoc"
    ADHERENCE = "lich_su_tuan_thu"
    INTERACTIONS = "canh_bao_tuong_tac"
    MEAL = "goi_y_bua_an"


# Purpose consent của patient cần có cho từng scope.
SCOPE_PURPOSE: dict[Scope, str] = {
    Scope.HEALTH_PROFILE: "health_data",
    Scope.MEDICATIONS: "health_data",
    Scope.ADHERENCE: "health_data",
    Scope.INTERACTIONS: "health_data",
    Scope.MEAL: "ai_meal",
}


class ActorRole(StrEnum):
    FAMILY = "family"
    ADMIN = "admin"
    NO_ACCESS = "khong_co_quyen"


@dataclass(frozen=True)
class AccessFacts:
    caller_id: UUID
    patient_id: UUID
    caller_is_admin: bool
    purpose_consent: bool  # consent của patient cho purpose của scope
    active_sharing_link: bool  # link active + sharing_enabled
    family_sharing_consent: bool  # consent family_sharing của patient


@dataclass(frozen=True)
class Decision:
    allowed: bool
    log_role: ActorRole | None  # None = không ghi access_logs (truy cập của chính chủ)
    reason: str | None = None


def decide(f: AccessFacts) -> Decision:
    if f.caller_id == f.patient_id:
        return Decision(f.purpose_consent, None, None if f.purpose_consent else "consent_revoked")
    if f.active_sharing_link and f.family_sharing_consent and f.purpose_consent:
        return Decision(True, ActorRole.FAMILY)
    if f.caller_is_admin:
        return Decision(True, ActorRole.ADMIN)
    return Decision(False, ActorRole.NO_ACCESS, "khong_co_quyen")
