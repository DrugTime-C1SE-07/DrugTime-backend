"""HTTP layer of POST /catalog/medications/match without a database (4.13)."""

import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from drugtime.main import create_app
from drugtime.modules.catalog.adapters.inbound import ocr_match_http as http
from drugtime.modules.identity import api as identity
from drugtime.shared.config import get_settings
from drugtime.shared.db import get_uow
from tests.unit.test_catalog_ocr_match_scoring import FakeReader, med

PATH = "/catalog/medications/match"
SENTINEL = "Zyqoxatriptan"


@pytest.fixture
def make_client(monkeypatch):
    def build(reader):
        app = create_app()
        app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
            uuid4(), False
        )
        app.dependency_overrides[get_uow] = lambda: None
        monkeypatch.setattr(http, "SqlCatalog", lambda: reader)
        return TestClient(app, raise_server_exceptions=True)

    return build


def test_matched_response_shape_and_no_store__AC12(make_client):
    reader = FakeReader([med(7, "Cefuroxim", "500 mg", "Cefuroxim axetil")])
    r = make_client(reader).post(PATH, json={"text": "CEFUROXIM 500mg\nCefuroxim"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"status", "items", "preselected_id", "suggested_query", "reasons"}
    assert body["status"] == "matched" and body["preselected_id"] == 7
    assert set(body["items"][0]) == {
        "id", "name", "active_ingredient", "strength_text", "dosage_form",
        "has_active_ingredients", "score",
    }
    assert body["items"][0]["active_ingredient"] == "Cefuroxim axetil"


def test_default_limit_comes_from_settings__AC10(make_client, monkeypatch):
    catalog = [med(i, f"Paracetamol {chr(64 + i)}", "500 mg") for i in range(1, 10)]
    client = make_client(FakeReader(catalog))
    assert len(client.post(PATH, json={"text": "Paracetamol 500mg"}).json()["items"]) == 5
    monkeypatch.setenv("OCR_MATCH_DEFAULT_LIMIT", "2")
    get_settings.cache_clear()
    try:
        assert len(client.post(PATH, json={"text": "Paracetamol 500mg"}).json()["items"]) == 2
        explicit = client.post(PATH, json={"text": "Paracetamol 500mg", "limit": 8})
        assert len(explicit.json()["items"]) == 8
    finally:
        monkeypatch.delenv("OCR_MATCH_DEFAULT_LIMIT")
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "body",
    [{}, {"text": ""}, {"text": " \n\t"}, {"text": "x" * 2001}, {"text": "a", "limit": 0},
     {"text": "a", "limit": 11}, {"text": "a", "extra": 1}],
)
def test_validation_error_has_no_store__AC9(make_client, body):
    r = make_client(FakeReader([])).post(PATH, json=body)
    assert r.status_code == 422
    assert r.headers["cache-control"] == "no-store"


def test_db_error_500_no_store_no_text_in_logs__AC7(make_client, caplog):
    class Failing(FakeReader):
        def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
            raise OperationalError(
                "SELECT ... LIKE %(pattern)s", {"pattern": query_key}, Exception()
            )

    caplog.set_level(logging.DEBUG)
    r = make_client(Failing([])).post(PATH, json={"text": f"{SENTINEL} 10mg"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error"}
    assert r.headers["cache-control"] == "no-store"
    assert SENTINEL.lower() not in caplog.text.lower()


def test_unauthenticated_401():
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: None
    r = TestClient(app).post(PATH, json={"text": "Panadol"})
    assert r.status_code == 401


def test_adherence_keeps_no_store_route():
    # The middleware set now has two routes; /adherence behaviour is unchanged.
    from drugtime import main

    assert ("GET", "/adherence") in main._NO_STORE_ROUTES
    assert ("POST", PATH) in main._NO_STORE_ROUTES
