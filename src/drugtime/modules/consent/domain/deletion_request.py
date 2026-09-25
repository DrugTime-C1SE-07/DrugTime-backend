from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class DeletionStatus(StrEnum):
    PENDING = "cho_duyet"
    APPROVED = "da_duyet"
    REJECTED = "tu_choi"
    COMPLETED = "hoan_tat"


@dataclass(frozen=True)
class DeletionRequest:
    id: UUID
    user_id: UUID
    status: DeletionStatus

    def can_execute(self) -> bool:
        return self.status is DeletionStatus.APPROVED
