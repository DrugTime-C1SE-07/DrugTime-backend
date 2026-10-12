"""Unit test tra cứu hoạt chất cho admin (task 2.16, AC12)."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.application.list_active_ingredients import (
    ActiveIngredient,
    ActiveIngredientPage,
    list_active_ingredients,
    normalize_query,
)
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow


class FakeReader:
    def __init__(self, page=None):
        self.calls = []
        self.page = page or ActiveIngredientPage(items=[], total=0)

    def list(self, uow, *, escaped, medication_id, skip, limit):
        self.calls.append(
            dict(escaped=escaped, medication_id=medication_id, skip=skip, limit=limit)
        )
        return self.page


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), ("", None), ("   ", None), (" war ", "war"), ("50%_x\\", "50\\%\\_x\\\\")],
)
def test_normalize_query_trims_and_escapes(raw, expected):
    assert normalize_query(raw) == expected


def test_list_passes_filters_to_reader():
    reader = FakeReader()
    list_active_ingredients(object(), reader, q=" Warf ", medication_id=7, skip=20, limit=10)
    assert reader.calls == [dict(escaped="Warf", medication_id=7, skip=20, limit=10)]


def _fake_uow():
    yield object()


def _client(*, user):
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    if user is not None:
        app.dependency_overrides[identity.current_user] = lambda: user
    return TestClient(app)


def test_requires_token_401():
    assert _client(user=None).get("/admin/active-ingredients").status_code == 401


def test_non_admin_403_admin_only():
    r = _client(user=identity.CurrentUser(id=uuid4(), is_admin=False)).get(
        "/admin/active-ingredients"
    )
    assert (r.status_code, r.json()) == (403, {"detail": "admin_only"})


def test_admin_gets_page_shape():
    page = ActiveIngredientPage(
        items=[ActiveIngredient(12, "Warfarin", "B01AA03", "Chống đông", ["Warfarin natri"])],
        total=1,
    )
    with patch(
        "drugtime.modules.catalog.adapters.inbound.http.SqlActiveIngredients",
        return_value=FakeReader(page),
    ):
        r = _client(user=identity.CurrentUser(id=uuid4(), is_admin=True)).get(
            "/admin/active-ingredients", params={"q": "war", "medication_id": 3}
        )
    assert r.status_code == 200
    assert r.json() == {
        "items": [
            {
                "id": 12,
                "standard_name": "Warfarin",
                "atc_code": "B01AA03",
                "pharmacological_group": "Chống đông",
                "aliases": ["Warfarin natri"],
            }
        ],
        "total": 1,
    }


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"skip": -1}, {"q": ""}])
def test_bad_query_422(params):
    r = _client(user=identity.CurrentUser(id=uuid4(), is_admin=True)).get(
        "/admin/active-ingredients", params=params
    )
    assert r.status_code == 422
