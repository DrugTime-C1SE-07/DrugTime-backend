from contextlib import contextmanager

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tests.integration.test_linked_patients_api import PATH, linked, logs

from drugtime.modules.access.adapters.inbound import linked_patients_http as http
from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit


@pytest.mark.parametrize("failure", ["second_insert", "commit"])
def test_audit_insert_or_commit_failure_never_returns_partial_list__AC5_AC10_AC14(
    client, make, auth, db, monkeypatch, failure
):
    caller = make.user()
    linked(make, caller)
    linked(make, caller)
    if failure == "second_insert":
        original, counter = SqlAccessLog.append_allowed, []

        def append(self, *args):
            counter.append(1)
            if len(counter) == 2:
                raise SQLAlchemyError("injected audit failure")
            return original(self, *args)

        monkeypatch.setattr(SqlAccessLog, "append_allowed", append)
    else:
        original = http.unit_of_work

        @contextmanager
        def fail_commit():
            with original() as uow:
                yield uow
                raise SQLAlchemyError("injected before commit")

        monkeypatch.setattr(http, "unit_of_work", fail_commit)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "service_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert logs(db, caller) == []
    assert make.family_audit_events(actor_id=caller) == []


@pytest.mark.parametrize("admin", [False, True])
def test_empty_or_denied_audit_failure_returns_503__AC5_AC6_AC11(
    client, make, auth, db, monkeypatch, admin
):
    caller = make.user(admin=admin)

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("injected audit unavailable")

    monkeypatch.setattr(SqlLinkAudit, "denied" if admin else "allowed", unavailable)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 503 and response.json() == {"detail": "service_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert make.family_audit_events(actor_id=caller) == []
    assert logs(db, caller) == []


@pytest.mark.parametrize("failure", ["database", "pep"])
def test_database_or_pep_read_failure_returns_503__AC5(
    client, make, auth, db, monkeypatch, failure
):
    caller = make.user()
    linked(make, caller)

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("injected read failure")

    target, method = (
        (http.LinkedPatientCandidates, "ids")
        if failure == "database"
        else (http.ModuleFactsReader, "read")
    )
    monkeypatch.setattr(target, method, unavailable)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 503 and response.json() == {"detail": "service_unavailable"}
    assert logs(db, caller) == []
