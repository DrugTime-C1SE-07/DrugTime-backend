import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from drugtime.modules.family.adapters.outbound import sql_link_attempts
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit
from drugtime.shared import db
from drugtime.shared.config import Settings


def test_primary_pool_uses_configured_limits(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "7.5")
    settings = Settings(_env_file=None)
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    db._primary_engine.cache_clear()
    engine = db.get_engine()
    try:
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 1
        assert engine.pool.timeout() == 7.5
        assert db.get_engine() is engine
    finally:
        engine.dispose()
        db._primary_engine.cache_clear()


def test_pool_defaults_bound_connections_per_process(monkeypatch):
    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_DENIED_AUDIT_POOL_SIZE",
        "DB_DENIED_AUDIT_MAX_OVERFLOW",
        "DB_DENIED_AUDIT_POOL_TIMEOUT",
        "DB_LINK_FAILURE_POOL_SIZE",
        "DB_LINK_FAILURE_MAX_OVERFLOW",
        "DB_LINK_FAILURE_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert (settings.db_pool_size, settings.db_max_overflow, settings.db_pool_timeout) == (3, 0, 30)
    assert (
        settings.db_link_failure_pool_size,
        settings.db_link_failure_max_overflow,
        settings.db_link_failure_pool_timeout,
    ) == (2, 0, 30)
    assert (
        settings.db_denied_audit_pool_size,
        settings.db_denied_audit_max_overflow,
        settings.db_denied_audit_pool_timeout,
    ) == (1, 0, 30)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("db_pool_size", 1),
        ("db_max_overflow", -1),
        ("db_pool_timeout", 0),
        ("db_pool_timeout", float("inf")),
        ("db_denied_audit_pool_size", 0),
        ("db_denied_audit_max_overflow", -1),
        ("db_denied_audit_pool_timeout", 0),
        ("db_denied_audit_pool_timeout", float("inf")),
        ("db_link_failure_pool_size", 0),
        ("db_link_failure_max_overflow", -1),
        ("db_link_failure_pool_timeout", -1),
        ("db_link_failure_pool_timeout", float("nan")),
    ],
)
def test_rejects_invalid_pool_configuration(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **{field: value})


def test_denied_audit_commits_when_primary_pool_is_full(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'audit.db'}"
    primary = create_engine(url, pool_size=3, max_overflow=0, pool_timeout=0.2)
    audit = create_engine(url, pool_size=1, max_overflow=0, pool_timeout=2)
    monkeypatch.setattr(db, "get_engine", lambda: primary)
    monkeypatch.setattr(db, "get_denied_audit_engine", lambda: audit)
    with primary.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE family_link_audit_events "
                "(actor_user_id TEXT, patient_user_id TEXT, link_id INT, operation TEXT, "
                "result TEXT, reason TEXT)"
            )
        )

    monkeypatch.setitem(sqlite3.adapters, (UUID, sqlite3.PrepareProtocol), str)
    outer_open = Barrier(3, timeout=5)
    writes_finished = Barrier(3, timeout=5)

    class RollBackRequest(Exception):
        pass

    def denied(actor):
        with pytest.raises(RollBackRequest), db.unit_of_work():
            outer_open.wait()
            try:
                SqlLinkAudit().denied(actor, None, None, "send", "test")
            finally:
                writes_finished.wait()
            raise RollBackRequest

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(denied, [uuid4() for _ in range(3)]))
        with primary.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM family_link_audit_events WHERE result='denied'")
                )
                == 3
            )
    finally:
        audit.dispose()
        primary.dispose()


def test_denied_audit_pool_uses_configured_limits(monkeypatch):
    monkeypatch.setenv("DB_DENIED_AUDIT_POOL_SIZE", "2")
    monkeypatch.setenv("DB_DENIED_AUDIT_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_DENIED_AUDIT_POOL_TIMEOUT", "4.5")
    settings = Settings(_env_file=None)
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    db._denied_audit_engine.cache_clear()
    db._primary_engine.cache_clear()
    engine = db.get_denied_audit_engine()
    primary = db.get_engine()
    try:
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 1
        assert engine.pool.timeout() == 4.5
        assert db.get_denied_audit_engine() is engine
        assert engine is not primary
    finally:
        engine.dispose()
        primary.dispose()
        db._denied_audit_engine.cache_clear()
        db._primary_engine.cache_clear()


@pytest.mark.parametrize(
    ("module", "get_engine", "cached_factory"),
    [
        (db, db.get_engine, db._primary_engine),
        (db, db.get_denied_audit_engine, db._denied_audit_engine),
        (
            sql_link_attempts,
            sql_link_attempts._failure_engine,
            sql_link_attempts._cached_failure_engine,
        ),
    ],
)
def test_engine_is_created_once_on_concurrent_first_use(
    monkeypatch, module, get_engine, cached_factory
):
    start = Barrier(4, timeout=5)
    calls = []

    def create(*args, **kwargs):
        engine = object()
        calls.append(engine)
        sleep(0.05)
        return engine

    def engine_after_barrier(_):
        start.wait()
        return get_engine()

    monkeypatch.setattr(module, "create_engine", create)
    cached_factory.cache_clear()
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            engines = list(executor.map(engine_after_barrier, range(4)))
        assert len(calls) == 1
        assert all(engine is calls[0] for engine in engines)
    finally:
        cached_factory.cache_clear()
