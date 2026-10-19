"""Unit test cho Admin Medication Catalog CRUD API (PB04, Task 2.13)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow
from drugtime.shared.errors import NotFound


def _fake_uow():
    yield object()


@pytest.fixture
def anonymous_client():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    return TestClient(app)


@pytest.fixture
def non_admin_client():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    return TestClient(app)


@pytest.fixture
def admin_client():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=True
    )
    return TestClient(app)


# --- 1. Kiểm tra xác thực và phân quyền (401 & 403) ---


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/admin/medications", {"name": "Panadol"}),
        ("get", "/admin/medications", None),
        ("get", "/admin/medications/1", None),
        ("patch", "/admin/medications/1", {"name": "New Name"}),
        ("delete", "/admin/medications/1", None),
    ],
)
def test_admin_endpoints_require_auth_401(anonymous_client, method, path, body):
    r = anonymous_client.request(method, path, json=body)
    assert r.status_code == 401


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/admin/medications", {"name": "Panadol"}),
        ("get", "/admin/medications", None),
        ("get", "/admin/medications/1", None),
        ("patch", "/admin/medications/1", {"name": "New Name"}),
        ("delete", "/admin/medications/1", None),
    ],
)
def test_admin_endpoints_reject_non_admin_403(non_admin_client, method, path, body):
    r = non_admin_client.request(method, path, json=body)
    assert r.status_code == 403
    assert r.json() == {"detail": "admin_only"}


# --- 2. Kiểm tra Pydantic Validation (422) ---


def test_create_validation_source_pair_enforced(admin_client):
    # source có nhưng source_ref là None -> 422
    r = admin_client.post(
        "/admin/medications",
        json={"name": "Paracetamol 500mg", "source": "dav_drugbank", "source_ref": None},
    )
    assert r.status_code == 422

    # source_ref có nhưng source là None -> 422
    r = admin_client.post(
        "/admin/medications",
        json={"name": "Paracetamol 500mg", "source": None, "source_ref": "REF-001"},
    )
    assert r.status_code == 422


def test_create_validation_empty_name_rejected(admin_client):
    r = admin_client.post(
        "/admin/medications",
        json={"name": ""},
    )
    assert r.status_code == 422


# --- 3. Kiểm tra các luồng CRUD thành công & 404 ---


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_create_medication_success(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.create.return_value = {
        "id": 101,
        "name": "Paracetamol 500mg",
        "raw_active_ingredient": "Paracetamol",
        "strength_text": "500mg",
        "dosage_form": "Viên nén",
        "manufacturer_name": "Dược Hậu Giang",
        "manufacturer_country": "Việt Nam",
        "packaging_spec": "Hộp 10 vỉ",
        "source": "dav_drugbank",
        "source_ref": "VN-12345-20",
        "deleted_at": None,
    }

    r = admin_client.post(
        "/admin/medications",
        json={
            "name": "Paracetamol 500mg",
            "raw_active_ingredient": "Paracetamol",
            "strength_text": "500mg",
            "dosage_form": "Viên nén",
            "manufacturer_name": "Dược Hậu Giang",
            "manufacturer_country": "Việt Nam",
            "packaging_spec": "Hộp 10 vỉ",
            "source": "dav_drugbank",
            "source_ref": "VN-12345-20",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["id"] == 101
    assert data["name"] == "Paracetamol 500mg"
    assert data["source_ref"] == "VN-12345-20"


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_list_medications_pagination_and_query(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.list_active.return_value = (
        [
            {
                "id": 1,
                "name": "Amlodipin 5mg",
                "raw_active_ingredient": "Amlodipin",
                "strength_text": "5mg",
                "dosage_form": "Viên",
                "manufacturer_name": None,
                "manufacturer_country": None,
                "packaging_spec": None,
                "source": None,
                "source_ref": None,
                "deleted_at": None,
            }
        ],
        1,
    )

    r = admin_client.get("/admin/medications?q=amlo&skip=0&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Amlodipin 5mg"


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_get_medication_detail(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.get_active.return_value = {
        "id": 42,
        "name": "Berberin",
        "raw_active_ingredient": None,
        "strength_text": None,
        "dosage_form": None,
        "manufacturer_name": None,
        "manufacturer_country": None,
        "packaging_spec": None,
        "source": None,
        "source_ref": None,
        "deleted_at": None,
    }

    r = admin_client.get("/admin/medications/42")
    assert r.status_code == 200
    assert r.json()["id"] == 42
    assert r.json()["name"] == "Berberin"


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_get_medication_not_found(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.get_active.return_value = None

    r = admin_client.get("/admin/medications/999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Medication not found"}


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_update_medication_success(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.update.return_value = {
        "id": 42,
        "name": "Berberin 100mg",
        "raw_active_ingredient": None,
        "strength_text": "100mg",
        "dosage_form": None,
        "manufacturer_name": None,
        "manufacturer_country": None,
        "packaging_spec": None,
        "source": None,
        "source_ref": None,
        "deleted_at": None,
    }

    r = admin_client.patch("/admin/medications/42", json={"name": "Berberin 100mg"})
    assert r.status_code == 200
    assert r.json()["name"] == "Berberin 100mg"


@patch("drugtime.modules.catalog.application.service.SqlCatalog")
def test_delete_medication_soft_delete(mock_sql_cls, admin_client):
    mock_repo = MagicMock()
    mock_sql_cls.return_value = mock_repo
    mock_repo.soft_delete.return_value = True

    r = admin_client.delete("/admin/medications/42")
    assert r.status_code == 204
    assert not r.content

    # Trường hợp đã xóa hoặc không tìm thấy:
    mock_repo.soft_delete.return_value = False
    r_not_found = admin_client.delete("/admin/medications/42")
    assert r_not_found.status_code == 404
