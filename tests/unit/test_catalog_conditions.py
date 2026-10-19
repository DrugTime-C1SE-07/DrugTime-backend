from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.adapters.inbound import conditions_http as http
from drugtime.modules.catalog.application.list_conditions import ConditionPage
from drugtime.modules.catalog.domain.condition import Condition
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(uuid4(), False)
    app.dependency_overrides[get_uow] = lambda: object()
    monkeypatch.setattr(
        http, "list_conditions", Mock(return_value=ConditionPage([Condition(1, "Diabetes")], 1))
    )
    return TestClient(app)


def test_catalog_authenticated_without_profile_pep(client):
    response = client.get("/conditions")
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": 1, "name": "Diabetes"}],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_pagination_bounds(client, query):
    assert client.get("/conditions?" + query).status_code == 422


def test_sql_catalog_order_and_offset():
    from drugtime.modules.catalog.adapters.outbound.sql_conditions import SqlConditions

    uow = MagicMock()
    uow.connection.execute.return_value.scalar_one.return_value = 200
    uow.connection.execute.return_value.__iter__ = lambda self: iter([])
    page = SqlConditions().list(uow, limit=10, offset=100)
    assert page.items == [] and page.total == 200
    statement, params = uow.connection.execute.call_args.args
    assert "ORDER BY id" in str(statement)
    assert params == {"limit": 10, "offset": 100}


def test_sql_catalog_get_and_batched_names():
    from types import SimpleNamespace

    from drugtime.modules.catalog.adapters.outbound.sql_conditions import SqlConditions

    uow = MagicMock()
    sql = SqlConditions()
    assert sql.names(uow, []) == {}
    uow.connection.execute.assert_not_called()
    uow.connection.execute.return_value.first.return_value = None
    assert sql.get(uow, 99) is None
    uow.connection.execute.return_value.first.return_value = (1, "Diabetes")
    assert sql.get(uow, 1) == Condition(1, "Diabetes")
    uow.connection.execute.return_value.__iter__.return_value = iter(
        [SimpleNamespace(id=1, name="Diabetes"), SimpleNamespace(id=2, name="Hypertension")]
    )
    assert sql.names(uow, [1, 2]) == {1: "Diabetes", 2: "Hypertension"}


@pytest.mark.parametrize("total,offset", [(0, 0), (3, 3), (3, 4), (3, 2**63), (3, 10**100)])
def test_offset_at_or_beyond_total_does_not_query_page(total, offset):
    from drugtime.modules.catalog.adapters.outbound.sql_conditions import SqlConditions

    uow = MagicMock()
    uow.connection.execute.return_value.scalar_one.return_value = total
    page = SqlConditions().list(uow, limit=20, offset=offset)
    assert page.items == [] and page.total == total
    uow.connection.execute.assert_called_once()
    assert "count(*)" in str(uow.connection.execute.call_args.args[0])


@pytest.mark.parametrize("offset", [7, 2**63, 10**100])
def test_http_out_of_range_offset_returns_empty_page(offset):
    app = create_app()
    uow = MagicMock()
    uow.connection.execute.return_value.scalar_one.return_value = 7
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(uuid4(), False)
    app.dependency_overrides[get_uow] = lambda: uow
    response = TestClient(app).get(f"/conditions?offset={offset}")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 7, "limit": 20, "offset": offset}
    uow.connection.execute.assert_called_once()
