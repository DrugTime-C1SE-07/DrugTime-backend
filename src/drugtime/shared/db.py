from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from drugtime.shared.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


class SqlUnitOfWork:
    """Một transaction. Mọi module ghi trong cùng một UoW thì cùng commit/rollback."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> Connection:
        return self._connection


@contextmanager
def unit_of_work() -> Iterator[SqlUnitOfWork]:
    with get_engine().begin() as conn:  # commit khi thoát bình thường, rollback khi có lỗi
        yield SqlUnitOfWork(conn)


def get_uow() -> Iterator[SqlUnitOfWork]:
    """FastAPI dependency: mỗi request một transaction."""
    with unit_of_work() as uow:
        yield uow
