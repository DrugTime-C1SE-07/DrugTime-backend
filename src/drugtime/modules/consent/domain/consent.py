"""Consent theo mục đích của chính người dùng (task 1.14). Hàm thuần, không I/O."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.errors import DomainError

DOCUMENT_OUTDATED = "consent_document_outdated"

# Phiên bản văn bản mô tả mục đích đang hiển thị trên app. Đổi văn bản thì đổi phiên bản.
CURRENT_DOCUMENT_VERSION: dict[Purpose, str] = {
    Purpose.HEALTH_DATA: "2026-10-v1",
    Purpose.FAMILY_SHARING: "2026-10-v1",
    Purpose.AI_MEAL: "2026-10-v1",
}


@dataclass(frozen=True)
class ActiveConsent:
    granted_at: datetime
    document_version: str


@dataclass(frozen=True)
class ConsentState:
    purpose: Purpose
    active: ActiveConsent | None

    @property
    def current_document_version(self) -> str:
        return CURRENT_DOCUMENT_VERSION[self.purpose]


def check_document_version(purpose: Purpose, document_version: str) -> None:
    """Chỉ nhận đúng phiên bản văn bản hiện hành của mục đích đó."""
    if document_version != CURRENT_DOCUMENT_VERSION[purpose]:
        raise DomainError(DOCUMENT_OUTDATED)


def states_for(active: Mapping[Purpose, ActiveConsent]) -> list[ConsentState]:
    """Đủ mọi mục đích, theo thứ tự khai báo của Purpose, kể cả mục đích chưa đồng ý."""
    return [ConsentState(p, active.get(p)) for p in Purpose]
