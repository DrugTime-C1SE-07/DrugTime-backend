"""Unit test lớp HTTP danh mục quy tắc tương tác (task 2.16): xác thực, 422 cấu trúc, mã lỗi,
luồng tạo → sửa → lịch sử → xóa qua service thật với store giả."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.interaction.application.manage_drug_food_interactions import (
    drug_food_interaction_service,
)
from drugtime.modules.interaction.application.manage_drug_interactions import (
    drug_interaction_service,
)
from drugtime.modules.interaction.domain.catalog_rules import DrugInteractionContent
from drugtime.shared.db import get_uow
from tests.unit.test_interaction_catalog_use_cases import FakeAdmins, FakeIngredients, FakeStore

HTTP = "drugtime.modules.interaction.adapters.inbound.http"
ADMIN = identity.CurrentUser(id=uuid4(), is_admin=True)
USER = identity.CurrentUser(id=uuid4(), is_admin=False)

DDI = {
    "ingredient_a_id": 1,
    "ingredient_b_id": 2,
    "interaction_type": "phu_thuoc_lieu",
    "severity_level": 2,
    "handling_type": "can_theo_doi",
    "description": "Tăng nguy cơ chảy máu.",
    "source": "QĐ 5948/QĐ-BYT",
    "dose_thresholds": [
        {
            "ingredient_ref": "B",
            "min_dose": 300,
            "dose_unit": "mg/ngày",
            "severity_level": 4,
            "warning_text": "Không phối hợp.",
        }
    ],
}
FOOD = {
    "ingredient_id": 1,
    "food_to_avoid": "Nước bưởi chùm",
    "severity_level": 3,
    "reason": "r",
    "source": "s",
}


def _fake_uow():
    yield object()


def _pair(c):
    if isinstance(c, DrugInteractionContent):
        return frozenset(c.ingredient_ids())
    return (c.ingredient_id, c.food_to_avoid.lower())


@pytest.fixture
def services():
    ddi = drug_interaction_service(FakeStore(_pair), FakeIngredients(), FakeAdmins())
    food = drug_food_interaction_service(FakeStore(_pair), FakeIngredients(), FakeAdmins())
    with patch(f"{HTTP}._ddi", return_value=ddi), patch(f"{HTTP}._food", return_value=food):
        yield ddi, food


def _client(user):
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    if user is not None:
        app.dependency_overrides[identity.current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def admin(services):
    return _client(ADMIN)


ROUTES = [
    ("post", "/admin/drug-interactions", DDI),
    ("get", "/admin/drug-interactions", None),
    ("get", "/admin/drug-interactions/1", None),
    ("patch", "/admin/drug-interactions/1", {"expected_version": 1, "severity_level": 3}),
    ("delete", "/admin/drug-interactions/1?expected_version=1", None),
    ("get", "/admin/drug-interactions/1/versions", None),
    ("get", "/admin/drug-interaction-versions/1", None),
    ("post", "/admin/drug-food-interactions", FOOD),
    ("get", "/admin/drug-food-interactions", None),
    ("get", "/admin/drug-food-interactions/1", None),
    ("patch", "/admin/drug-food-interactions/1", {"expected_version": 1, "severity_level": 3}),
    ("delete", "/admin/drug-food-interactions/1?expected_version=1", None),
    ("get", "/admin/drug-food-interactions/1/versions", None),
    ("get", "/admin/drug-food-interaction-versions/1", None),
]


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_missing_token_401(services, method, path, body):
    assert _client(None).request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_non_admin_403_admin_only(services, method, path, body):
    r = _client(USER).request(method, path, json=body)
    assert (r.status_code, r.json()) == (403, {"detail": "admin_only"})


def test_create_returns_contract_shape(admin):
    r = admin.post("/admin/drug-interactions", json=DDI)
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1 and body["state"] == "current"
    assert body["verification_status"] == "da_xac_minh"
    assert body["ingredient_a"] == {"id": 1, "standard_name": "ingredient-1"}
    assert body["ingredient_b_external_name"] is None
    assert body["updated_by"] == {"id": str(ADMIN.id), "email": "admin@test.local"}
    assert body["deleted_by"] is None and body["superseded_at"] is None
    assert body["dose_thresholds"][0]["min_dose"] == 300
    assert body["dose_thresholds"][0]["max_dose"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"verification_status": "da_xac_minh"},  # field lạ (AC15)
        {"ingredient_b_external_name": "Rượu"},  # gửi cả hai B
        {"ingredient_b_id": None},  # B id null
        {"severity_level": 5},
        {"severity_level": 0},
        {"min_interval_hours": 0},
        {"min_interval_hours": 169},
        {"handling_type": "doi_gio"},
        {"description": "   "},
        {"source": ""},
        {"dose_thresholds": [{**DDI["dose_thresholds"][0], "min_dose": -1}]},
        {
            "dose_thresholds": [
                {"ingredient_ref": "A", "dose_unit": "mg", "severity_level": 2, "warning_text": "w"}
            ]
        },
        {"dose_thresholds": [{**DDI["dose_thresholds"][0], "ingredient_ref": "C"}]},
        {"dose_thresholds": [DDI["dose_thresholds"][0]] * 21},
    ],
)
def test_create_structure_errors_422(admin, services, change):
    r = admin.post("/admin/drug-interactions", json={**DDI, **change})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)
    assert services[0].store.calls == []


def test_create_without_b_422(admin):
    body = {k: v for k, v in DDI.items() if k != "ingredient_b_id"}
    assert admin.post("/admin/drug-interactions", json=body).status_code == 422


@pytest.mark.parametrize(
    "change, code",
    [
        ({"ingredient_b_id": 1}, "same_ingredient"),
        ({"ingredient_b_id": 99}, "active_ingredient_not_found"),
        ({"interaction_type": "chong_chi_dinh"}, "contraindication_severity_mismatch"),
        (
            {"interaction_type": "chong_chi_dinh", "severity_level": 4},
            "threshold_not_allowed",
        ),
        ({"min_interval_hours": 2}, "min_interval_not_allowed"),
    ],
)
def test_create_business_errors_422(admin, change, code):
    r = admin.post("/admin/drug-interactions", json={**DDI, **change})
    assert (r.status_code, r.json()) == (422, {"detail": code})


@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": 1},  # không có field nào để sửa
        {"severity_level": 3},  # thiếu expected_version
        {"expected_version": 0, "severity_level": 3},
        {"expected_version": 1, "ingredient_a_id": 3},  # đổi cặp (AC9)
        {"expected_version": 1, "ingredient_b_external_name": "Rượu"},
        {"expected_version": 1, "verification_status": "x"},  # AC16
        {"expected_version": 1, "severity_level": None},  # null cho field không nullable
    ],
)
def test_update_structure_errors_422(admin, body):
    rid = admin.post("/admin/drug-interactions", json=DDI).json()["id"]
    r = admin.patch(f"/admin/drug-interactions/{rid}", json=body)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_full_flow_versions_conflicts_delete(admin):
    created = admin.post("/admin/drug-interactions", json=DDI).json()
    rid = created["id"]
    assert admin.post("/admin/drug-interactions", json=DDI).json() == {
        "detail": "interaction_rule_exists"
    }

    r = admin.patch(
        f"/admin/drug-interactions/{rid}", json={"expected_version": 1, "severity_level": 3}
    )
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["id"] == rid
    assert r.json()["dose_thresholds"][0]["id"] != created["dose_thresholds"][0]["id"]

    stale = admin.patch(
        f"/admin/drug-interactions/{rid}", json={"expected_version": 1, "source": "x"}
    )
    assert (stale.status_code, stale.json()) == (409, {"detail": "version_conflict"})

    history = admin.get(f"/admin/drug-interactions/{rid}/versions").json()["items"]
    assert [(v["version"], v["state"]) for v in history] == [(2, "current"), (1, "superseded")]
    old = admin.get(f"/admin/drug-interaction-versions/{created['version_id']}").json()
    assert old["severity_level"] == 2 and old["state"] == "superseded"

    assert admin.delete(f"/admin/drug-interactions/{rid}?expected_version=1").status_code == 409
    r = admin.delete(f"/admin/drug-interactions/{rid}?expected_version=2")
    assert (r.status_code, r.content) == (204, b"")
    assert admin.get(f"/admin/drug-interactions/{rid}").json() == {
        "detail": "interaction_rule_not_found"
    }
    assert admin.get("/admin/drug-interactions").json() == {"items": [], "total": 0}
    assert admin.get(f"/admin/drug-interactions/{rid}/versions").json()["items"][0]["state"] == (
        "deleted"
    )


def test_not_found_codes(admin):
    assert admin.get("/admin/drug-interactions/777").json() == {
        "detail": "interaction_rule_not_found"
    }
    assert admin.get("/admin/drug-interaction-versions/777").json() == {
        "detail": "interaction_version_not_found"
    }
    r = admin.delete("/admin/drug-interactions/777?expected_version=1")
    assert r.status_code == 404


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "skip=-1", "severity_level=5", "interaction_type=x", "q="],
)
def test_list_query_errors_422(admin, query):
    assert admin.get(f"/admin/drug-interactions?{query}").status_code == 422


def test_delete_requires_expected_version(admin):
    assert admin.delete("/admin/drug-interactions/1").status_code == 422


def test_food_flow(admin):
    created = admin.post("/admin/drug-food-interactions", json=FOOD)
    assert created.status_code == 201
    rid = created.json()["id"]
    assert created.json()["ingredient"] == {"id": 1, "standard_name": "ingredient-1"}
    dup = admin.post(
        "/admin/drug-food-interactions", json={**FOOD, "food_to_avoid": "nước BƯỞI chùm"}
    )
    assert (dup.status_code, dup.json()) == (409, {"detail": "interaction_rule_exists"})
    bad = admin.patch(
        f"/admin/drug-food-interactions/{rid}", json={"expected_version": 1, "ingredient_id": 2}
    )
    assert bad.status_code == 422
    r = admin.patch(
        f"/admin/drug-food-interactions/{rid}", json={"expected_version": 1, "severity_level": 4}
    )
    assert r.json()["version"] == 2
    unknown = admin.post("/admin/drug-food-interactions", json={**FOOD, "ingredient_id": 42})
    assert unknown.json() == {"detail": "active_ingredient_not_found"}
