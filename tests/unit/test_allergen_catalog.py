from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.adapters.inbound import allergens_http
from drugtime.modules.catalog.adapters.outbound.sql_allergens import SqlAllergens
from drugtime.modules.catalog.domain.allergen import Allergen
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow


class _Rows(list):
    """Minimal stand-in for a SQLAlchemy result: iterable rows with attribute access."""


class _Row(tuple):
    @property
    def id(self):
        return self[0]


def _uow(rows=()):
    uow = Mock()
    uow.connection.execute.return_value = _Rows(_Row(r) for r in rows)
    return uow


def _sql(uow) -> str:
    return " ".join(str(uow.connection.execute.call_args.args[0]).split())


def test_list_active_orders_drug_then_food_then_display_order():
    uow = _uow([("penicillin", "drug", "Penicillin", 1, True)])
    items = SqlAllergens().list_active(uow)
    assert items == [Allergen("penicillin", "drug", "Penicillin", 1, True)]
    assert "ORDER BY CASE category WHEN 'drug' THEN 0 ELSE 1 END, display_order, id" in _sql(uow)


def test_list_active_excludes_inactive():
    uow = _uow()
    SqlAllergens().list_active(uow)
    assert "WHERE is_active" in _sql(uow)
    active = _uow([("milk",)])
    assert SqlAllergens().active_ids(active, ["milk", "retired_one"]) == {"milk"}
    assert "WHERE is_active AND id = ANY(:ids)" in _sql(active)


def test_labels_include_retired_entries_and_skip_db_for_empty_input():
    uow = _uow([("retired_one", "food", "Cũ", 3, False)])
    assert SqlAllergens().labels(uow, ["retired_one"]) == {
        "retired_one": Allergen("retired_one", "food", "Cũ", 3, False)
    }
    assert "is_active" not in _sql(uow).split("WHERE", 1)[1]
    empty = _uow()
    assert SqlAllergens().labels(empty, []) == {}
    assert SqlAllergens().active_ids(empty, []) == set()
    empty.connection.execute.assert_not_called()


def _client(monkeypatch, items):
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(uuid4(), False)
    app.dependency_overrides[get_uow] = lambda: object()
    monkeypatch.setattr(allergens_http.SqlAllergens, "list_active", lambda _self, _uow: items)
    return TestClient(app)


def test_router_returns_active_items_in_adapter_order(monkeypatch):
    items = [
        Allergen("penicillin", "drug", "Penicillin", 1, True),
        Allergen("seafood", "food", "Hải sản", 1, True),
    ]
    with _client(monkeypatch, items) as client:
        response = client.get("/allergens")
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"id": "penicillin", "category": "drug", "name": "Penicillin"},
            {"id": "seafood", "category": "food", "name": "Hải sản"},
        ]
    }


def test_router_rejects_query_params(monkeypatch):
    with _client(monkeypatch, []) as client:
        response = client.get("/allergens", params={"category": "drug"})
    assert response.status_code == 422
