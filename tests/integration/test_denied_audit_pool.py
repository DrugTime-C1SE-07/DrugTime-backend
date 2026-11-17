from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text

from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog
from drugtime.modules.access.domain.rules import ActorRole, Scope
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit
from drugtime.shared import db as db_module


@pytest.mark.parametrize("kind", ["access", "family"])
def test_denied_audit_commits_when_request_pool_is_full(db, make, monkeypatch, kind):
    actors = [make.user() for _ in range(3)]
    primary = create_engine(
        db_module.get_engine().url,
        pool_size=3,
        max_overflow=0,
        pool_timeout=1,
    )
    monkeypatch.setattr(db_module, "get_engine", lambda: primary)
    outer_open = Barrier(len(actors), timeout=10)
    writes_finished = Barrier(len(actors), timeout=10)

    class RollBackRequest(Exception):
        pass

    def deny(actor):
        with pytest.raises(RollBackRequest), db_module.unit_of_work():
            outer_open.wait()
            try:
                if kind == "access":
                    SqlAccessLog().append_denied(
                        actor, ActorRole.PATIENT, actor, Scope.ADHERENCE, "consent_revoked"
                    )
                else:
                    SqlLinkAudit().denied(actor, None, None, "list_pending", "khong_co_quyen")
            finally:
                writes_finished.wait()
            raise RollBackRequest

    try:
        with ThreadPoolExecutor(max_workers=len(actors)) as executor:
            list(executor.map(deny, actors))
    finally:
        primary.dispose()

    if kind == "access":
        for actor in actors:
            assert [entry["result"] for entry in make.access_logs(actor)] == ["denied"]
    else:
        for actor in actors:
            results = (
                db.execute(
                    text(
                        "SELECT result FROM family_link_audit_events WHERE actor_user_id = :actor"
                    ),
                    {"actor": actor},
                )
                .scalars()
                .all()
            )
            assert results == ["denied"]
