from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    is_admin: bool


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    is_admin: bool
    erased: bool
