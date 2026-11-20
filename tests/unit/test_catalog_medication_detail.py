"""GET /catalog/medications/{id} (adhoc-20261120-add-medication-ux): use case, HTTP, không DB."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.application.get_medication_detail import get_medication_detail
from drugtime.modules.catalog.domain.medication import CatalogMedicationDetail
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow
from drugtime.shared.errors import NotFound

FULL = CatalogMedicationDetail(
    id=1007,
    name="Amlodipin 5mg",
    active_ingredient="Amlodipin besilat",
    strength_text="5 mg",
    dosage_form="Viên nén",
    manufacturer_name="Công ty CP Dược phẩm ABC",
    manufacturer_country="Việt Nam",
    packaging_spec="Hộp 3 vỉ x 10 viên",
    source="dav_drugbank",
)
SPARSE = CatalogMedicationDetail(
    id=2210,
    name="Melas",
    active_ingredient="Hydroquinone",
    strength_text="0,04",
    dosage_form="Kem bôi da",
    manufacturer_name=None,
    manufacturer_country=None,
    packaging_spec=None,
    source=None,
)


def _uow():
    yield object()


@pytest.fixture
def anonymous():
    app = create_app()
    app.dependency_overrides[get_uow] = _uow
    return TestClient(app)


@pytest.fixture
def signed_in(anonymous):
    anonymous.app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    return anonymous


def test_use_case_returns_detail():
    source = Mock(get_detail=Mock(return_value=FULL))
    assert get_medication_detail(object(), 1007, source) is FULL
    source.get_detail.assert_called_once()


def test_use_case_raises_not_found__AC17():
    source = Mock(get_detail=Mock(return_value=None))
    with pytest.raises(NotFound, match="^catalog_medication_not_found$"):
        get_medication_detail(object(), 99, source)


def test_route_returns_contract_shape__AC16(signed_in, monkeypatch):
    monkeypatch.setattr(SqlCatalog, "get_detail", Mock(return_value=FULL))
    r = signed_in.get("/catalog/medications/1007")
    assert r.status_code == 200
    assert r.json() == {
        "id": 1007,
        "name": "Amlodipin 5mg",
        "active_ingredient": "Amlodipin besilat",
        "strength_text": "5 mg",
        "dosage_form": "Viên nén",
        "manufacturer_name": "Công ty CP Dược phẩm ABC",
        "manufacturer_country": "Việt Nam",
        "packaging_spec": "Hộp 3 vỉ x 10 viên",
        "source": "dav_drugbank",
    }


def test_route_keeps_missing_fields_null_and_strength_raw__AC16(signed_in, monkeypatch):
    monkeypatch.setattr(SqlCatalog, "get_detail", Mock(return_value=SPARSE))
    body = signed_in.get("/catalog/medications/2210").json()
    assert body["strength_text"] == "0,04"  # không chuẩn hóa hay quy đổi (QD-38)
    assert body["manufacturer_name"] is None
    assert body["manufacturer_country"] is None
    assert body["packaging_spec"] is None
    assert body["source"] is None


def test_route_404_when_missing__AC17(signed_in, monkeypatch):
    monkeypatch.setattr(SqlCatalog, "get_detail", Mock(return_value=None))
    r = signed_in.get("/catalog/medications/99")
    assert r.status_code == 404
    assert r.json() == {"detail": "catalog_medication_not_found"}


def test_route_401_without_token__AC17(anonymous):
    r = anonymous.get("/catalog/medications/1007")
    assert r.status_code == 401
    assert r.json() == {"detail": "Missing bearer token"}


@pytest.mark.parametrize("bad", ["abc", "0", "-1"])
def test_route_422_for_non_positive_or_non_integer_id(signed_in, bad):
    r = signed_in.get(f"/catalog/medications/{bad}")
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["path", "id"]


def test_match_route_is_not_shadowed(signed_in):
    # GET /catalog/medications/{id} không được nuốt "match": POST match vẫn là route riêng.
    r = signed_in.get("/catalog/medications/match")
    assert r.status_code == 422  # "match" không phải số nguyên, không phải 405/200
    paths = signed_in.app.openapi()["paths"]
    assert "post" in paths["/catalog/medications/match"]
    assert set(paths["/catalog/medications/{id}"]) == {"get"}
