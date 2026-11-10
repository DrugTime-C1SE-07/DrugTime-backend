from typing import Protocol
from uuid import UUID

from drugtime.modules.access.domain.rules import AccessFacts, ActorRole, Scope
from drugtime.shared.uow import UnitOfWork


class FactsReader(Protocol):
    """Đọc trực tiếp từ family và consent ở mỗi request, không cache (CD2)."""

    def read(
        self,
        uow: UnitOfWork,
        caller_id: UUID,
        caller_is_admin: bool,
        patient_id: UUID,
        scope: Scope,
    ) -> AccessFacts: ...
    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...
    def has_consent(self, uow: UnitOfWork, user_id: UUID, purpose: str) -> bool: ...


class AccessLog(Protocol):
    def append_allowed(
        self, uow: UnitOfWork, actor_id: UUID, role: ActorRole, patient_id: UUID, scope: Scope
    ) -> None: ...
    def append_denied(
        self, actor_id: UUID, role: ActorRole, patient_id: UUID, scope: Scope, reason: str
    ) -> None:
        """Ghi ở transaction riêng để dòng denied còn lại dù request bị rollback."""
        ...


class PatientCandidates(Protocol):
    def ids(self, uow: UnitOfWork, family_id: UUID) -> list[UUID]: ...


class PatientNames(Protocol):
    def get(self, uow: UnitOfWork, patient_ids: list[UUID]) -> dict[UUID, str | None]: ...


class PatientListAudit(Protocol):
    def empty(self, uow: UnitOfWork, actor_id: UUID) -> None: ...
    def denied(self, actor_id: UUID) -> None:
        """Persist request-level denial in an independent transaction, without a patient."""
        ...
