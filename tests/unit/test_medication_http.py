"""Lớp HTTP của /medications không cần DB: 401 khi thiếu token, 422 khi sai cấu trúc."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow

VALID = {
    "client_uuid": str(uuid4()),
    "medication_id": 1,
    "quantity_per_dose": 1,
    "dosing_mode": "scheduled",
    "intake_times": ["08:00", "20:00"],
}


def _fake_uow():
    yield object()


@pytest.fixture
def anonymous():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    return TestClient(app)


@pytest.fixture
def signed_in():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/medications", VALID),
        ("post", "/medications", {"quantity_per_dose": 0}),  # body sai vẫn 401
        ("get", "/medications/1", None),
        ("patch", "/medications/1", {"stopped": True}),
        ("patch", "/medications/1", {}),
        ("get", "/medications", None),
        ("delete", "/medications/1", None),
        ("get", "/catalog/medications?q=amlo", None),
        ("get", "/catalog/medications?q=", None),  # q sai vẫn 401
        ("post", "/doses/batch", []),
        ("post", "/medications/1/schedules", {"intake_time": "12:00"}),
        ("patch", "/medications/1/schedules/2", {"reminder_enabled": False}),
        ("delete", "/medications/1/schedules/2", None),
        ("get", f"/patients/{uuid4()}/schedules", None),
    ],
)
def test_missing_authorization_401(anonymous, method, path, body):
    r = anonymous.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json() == {"detail": "Missing bearer token"}


def test_bad_scheme_401(anonymous):
    r = anonymous.get("/medications/1", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def _without(key):
    return {k: v for k, v in VALID.items() if k != key}


@pytest.mark.parametrize(
    "body, loc",
    [
        (_without("client_uuid"), "client_uuid"),
        ({**VALID, "client_uuid": "not-a-uuid"}, "client_uuid"),
        ({**VALID, "client_uuid": uuid4().hex}, "client_uuid"),  # thiếu gạch nối
        ({**VALID, "quantity_per_dose": 0}, "quantity_per_dose"),
        ({**VALID, "quantity_per_dose": 10.5}, "quantity_per_dose"),
        ({**VALID, "medication_id": 0}, "medication_id"),
        ({**VALID, "dosing_mode": "daily"}, "dosing_mode"),
        ({**VALID, "intake_times": ["24:00"]}, "intake_times"),
        ({**VALID, "intake_times": ["8:00"]}, "intake_times"),
        ({**VALID, "intake_times": ["08:00", "08:00"]}, "intake_times"),
        ({**VALID, "intake_times": [f"0{i}:00" for i in range(7)]}, "intake_times"),
        ({**VALID, "intake_times": []}, "intake_times"),
        ({**VALID, "intake_times": None}, "intake_times"),
        ({**VALID, "days_of_week": [0]}, "days_of_week"),
        ({**VALID, "days_of_week": [1, 1]}, "days_of_week"),
        ({**VALID, "max_doses_per_day": 7}, "max_doses_per_day"),
        ({**VALID, "intake_timing": "with_meal"}, "intake_timing"),
        ({**VALID, "stock_quantity": -1}, "stock_quantity"),
        ({**VALID, "stock_quantity": 10000}, "stock_quantity"),
        ({**VALID, "patient_id": str(uuid4())}, "patient_id"),
    ],
)
def test_create_structural_errors_422_array(signed_in, body, loc):
    r = signed_in.post("/medications", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert any(loc in e["loc"] for e in detail), detail


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"stopped": None},
        {"stopped": "false"},
        {"stopped": 0},
        {"quantity_per_dose": None},
        {"dosing_mode": None},
        {"medication_id": 2},
        {"intake_times": ["07:00", "07:00"]},
    ],
)
def test_update_structural_errors_422_array(signed_in, body):
    r = signed_in.patch("/medications/1", json=body)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_path_id_must_be_positive_int(signed_in):
    assert signed_in.get("/medications/0").status_code == 422
    assert signed_in.get("/medications/abc").status_code == 422


def test_delete_path_id_must_be_positive_int(signed_in):
    assert signed_in.delete("/medications/0").status_code == 422
    assert signed_in.delete("/medications/abc").status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "",  # thiếu q
        "?q=",
        "?q=%20%20%20",  # toàn khoảng trắng
        "?q=" + "a" * 101,
        "?q=amlo&limit=0",
        "?q=amlo&limit=51",
        "?q=amlo&limit=abc",
    ],
)
def test_catalog_search_query_errors_422_array(signed_in, query):
    r = signed_in.get("/catalog/medications" + query)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


# --- task 2.04 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/medications/1/schedules", {}),
        ("post", "/medications/1/schedules", {"intake_time": "24:00"}),
        ("post", "/medications/1/schedules", {"intake_time": "8:00"}),
        ("post", "/medications/1/schedules", {"intake_time": None}),
        ("post", "/medications/1/schedules", {"intake_time": "08:00", "days_of_week": [1]}),
        ("post", "/medications/1/schedules", {"intake_time": "08:00", "reminder_enabled": "false"}),
        ("patch", "/medications/1/schedules/2", {}),
        ("patch", "/medications/1/schedules/2", {"intake_time": "12:60"}),
        ("patch", "/medications/1/schedules/2", {"intake_time": None}),
        ("patch", "/medications/1/schedules/2", {"reminder_enabled": None}),
        ("patch", "/medications/1/schedules/2", {"reminder_enabled": 0}),
        ("patch", "/medications/1/schedules/2", {"days_of_week": [1, 2]}),
        ("patch", "/medications/1/schedules/0", {"reminder_enabled": True}),
        ("delete", "/medications/1/schedules/0", None),
        ("delete", "/medications/0/schedules/1", None),
    ],
)
def test_schedule_structural_errors_422_array(signed_in, method, path, body):
    r = signed_in.request(method, path, json=body)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("days", [[], [0], [8], [1, 1], None])
def test_update_days_of_week_structural_errors(signed_in, days):
    r = signed_in.patch("/medications/1", json={"days_of_week": days})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_patient_id_must_be_uuid(signed_in):
    r = signed_in.get("/patients/abc/schedules")
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "limit=x", "cursor="])
def test_limit_and_cursor_bounds_422(signed_in, query):
    r = signed_in.get(f"/patients/{uuid4()}/schedules?{query}")
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
