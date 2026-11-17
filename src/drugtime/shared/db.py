from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from threading import Lock

from sqlalchemy import Connection, Engine, create_engine

from drugtime.shared.config import get_settings

_engine_lock = Lock()


def get_engine() -> Engine:
    with _engine_lock:
        return _primary_engine()


@lru_cache
def _primary_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


def get_denied_audit_engine() -> Engine:
    with _engine_lock:
        return _denied_audit_engine()


@lru_cache
def _denied_audit_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_denied_audit_pool_size,
        max_overflow=settings.db_denied_audit_max_overflow,
        pool_timeout=settings.db_denied_audit_pool_timeout,
        pool_pre_ping=True,
    )


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


@contextmanager
def read_unit_of_work() -> Iterator[SqlUnitOfWork]:
    """Return the connection without committing a read-only lookup."""
    with get_engine().connect() as conn:
        yield SqlUnitOfWork(conn)


@contextmanager
def denied_audit_unit_of_work() -> Iterator[SqlUnitOfWork]:
    """Commit denied audit independently while the request still holds its connection."""
    with get_denied_audit_engine().begin() as conn:
        yield SqlUnitOfWork(conn)


def get_uow() -> Iterator[SqlUnitOfWork]:
    """FastAPI dependency: mỗi request một transaction."""
    with unit_of_work() as uow:
        yield uow
