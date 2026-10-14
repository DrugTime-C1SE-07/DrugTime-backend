from dataclasses import dataclass
from typing import Protocol

from drugtime.modules.catalog.domain.condition import Condition
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class ConditionPage:
    items: list[Condition]
    total: int


class ConditionReader(Protocol):
    def list(self, uow: UnitOfWork, *, limit: int, offset: int) -> ConditionPage: ...


def list_conditions(
    uow: UnitOfWork, reader: ConditionReader, *, limit: int = 20, offset: int = 0
) -> ConditionPage:
    return reader.list(uow, limit=limit, offset=offset)
