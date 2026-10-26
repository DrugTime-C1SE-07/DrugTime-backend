from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.identity import api as identity
from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers


class Connection:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params):
        self.calls.append((str(sql), params))
        return self.rows


def test_display_names_minimal_projection_batches_and_normalizes_names():
    ids = [uuid4() for _ in range(6)]
    rows = [
        SimpleNamespace(id=i, full_name=n)
        for i, n in zip(ids, ["  Nguyen An  ", "", " \t\n ", None], strict=False)
    ]
    c = Connection(rows)
    result = SqlUsers(SimpleNamespace(connection=c)).display_names(ids + [ids[0]])
    assert result == {ids[0]: "Nguyen An", ids[1]: None, ids[2]: None, ids[3]: None}
    assert ids[4] not in result
    assert len(c.calls) == 1
    sql, params = c.calls[0]
    assert "SELECT id, full_name FROM users" in sql and "erased_at IS NULL" in sql
    assert set(params["ids"]) == set(ids) and len(params["ids"]) == len(ids)
    assert all(field not in sql for field in ("email", "phone", "gender", "date_of_birth"))


def test_empty_names_does_not_query_database():
    c = Connection([])
    assert SqlUsers(SimpleNamespace(connection=c)).display_names([]) == {}
    assert not c.calls


def test_public_display_names_delegates_minimal_projection(monkeypatch):
    ids, uow = [uuid4()], object()
    seen = []
    monkeypatch.setattr(
        identity,
        "SqlUsers",
        lambda given: (
            seen.append(given)
            or SimpleNamespace(display_names=lambda given_ids: {given_ids[0]: None})
        ),
    )
    assert identity.display_names(uow, ids) == {ids[0]: None} and seen == [uow]
