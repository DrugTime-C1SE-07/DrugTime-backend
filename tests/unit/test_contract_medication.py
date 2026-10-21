"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay api_contract/openapi.json (task 2.01).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
OPERATIONS = [
    ("get", "/medications"),
    ("post", "/medications"),
    ("get", "/medications/{id}"),
    ("patch", "/medications/{id}"),
    ("delete", "/medications/{id}"),
    ("post", "/medications/{id}/schedules"),
    ("patch", "/medications/{id}/schedules/{schedule_id}"),
    ("delete", "/medications/{id}/schedules/{schedule_id}"),
    ("get", "/patients/{patient_id}/schedules"),
    ("get", "/catalog/medications"),
    ("get", "/medications/search"),
]

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def _resolve(spec, node):
    while "$ref" in node:
        name = node["$ref"].split("/")[-1]
        node = spec["components"]["schemas"][name]
    return node


def _object(spec, node):
    """Schema object sau khi bỏ $ref và nhánh null của anyOf."""
    node = _resolve(spec, node)
    for branch in node.get("anyOf", []):
        if branch.get("type") != "null":
            return _object(spec, branch)
    return node


def _shape(spec, node, depth=0):
    """(tên field, field bắt buộc, shape của field con kiểu object/array object)."""
    node = _object(spec, node)
    if node.get("type") == "array":
        return _shape(spec, node["items"], depth)
    props = node.get("properties")
    if not props or depth > 3:
        return None
    return (
        sorted(props),
        sorted(node.get("required", [])),
        {k: _shape(spec, v, depth + 1) for k, v in sorted(props.items())},
    )


def _request(spec, op):
    return op["requestBody"]["content"]["application/json"]["schema"]


def _response(spec, op, code):
    return op["responses"][code]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_operations_match_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]

    assert set(c_op["responses"]) <= set(a_op["responses"]), path
    if "requestBody" in c_op:
        assert _shape(contract, _request(contract, c_op)) == _shape(app, _request(app, a_op))
    for code in ("200", "201"):
        if code in c_op["responses"]:
            assert _shape(contract, _response(contract, c_op, code)) == _shape(
                app, _response(app, a_op, code)
            ), (method, path, code)


def test_request_bodies_forbid_unknown_fields(specs):
    _, app = specs
    for method, path in OPERATIONS:
        op = app["paths"][path][method]
        if "requestBody" in op:
            assert _object(app, _request(app, op)).get("additionalProperties") is False


def _query_params(op):
    return {
        p["name"]: (p.get("required", False), {k: p["schema"].get(k) for k in BOUNDS})
        for p in op.get("parameters", [])
        if p["in"] == "query"
    }


BOUNDS = ("minLength", "maxLength", "pattern", "minimum", "maximum", "default")


@pytest.mark.parametrize("path", ["/catalog/medications", "/medications/search"])
def test_catalog_search_query_params_match_contract(specs, path):
    contract, app = specs
    assert _query_params(contract["paths"][path]["get"]) == _query_params(app["paths"][path]["get"])


def test_catalog_search_operation_ids_match_contract(specs):
    contract, app = specs
    paths = ("/catalog/medications", "/medications/search")
    actual = [app["paths"][path]["get"]["operationId"] for path in paths]
    assert actual == [contract["paths"][path]["get"]["operationId"] for path in paths]
    assert len(set(actual)) == len(paths)


@pytest.fixture
def catalog_client():
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: object()
    return TestClient(app)


@pytest.mark.parametrize("path", ["/catalog/medications", "/medications/search"])
def test_catalog_search_requires_auth(catalog_client, path):
    response = catalog_client.get(path, params={"q": "amlo"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing bearer token"}


def test_catalog_search_alias_returns_same_catalog_without_id_collision(
    catalog_client, monkeypatch
):
    catalog_client.app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    search = Mock(
        return_value=[
            CatalogMedication(1, "Amlodipin 5mg", "5 mg", "Viên nén", True, "Amlodipin besilat")
        ]
    )
    monkeypatch.setattr(SqlCatalog, "search", search)
    responses = [
        catalog_client.get(path, params={"q": "  amlo  "})
        for path in ("/catalog/medications", "/medications/search")
    ]
    assert all(response.status_code == 200 for response in responses)
    assert (
        responses[0].json()
        == responses[1].json()
        == {
            "items": [
                {
                    "id": 1,
                    "name": "Amlodipin 5mg",
                    "active_ingredient": "Amlodipin besilat",
                    "strength_text": "5 mg",
                    "dosage_form": "Viên nén",
                }
            ]
        }
    )
    assert search.call_count == 2
    assert all(call.args[1:] == ("amlo", 20) for call in search.call_args_list)


@pytest.mark.parametrize("path", ["/catalog/medications", "/medications/search"])
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "a" * 101},
        {"q": "a", "limit": 0},
        {"q": "a", "limit": 51},
        {"q": "a", "limit": "invalid"},
    ],
)
def test_catalog_search_rejects_invalid_query(catalog_client, monkeypatch, path, params):
    catalog_client.app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    search = Mock(side_effect=AssertionError("Invalid query must not reach the catalog"))
    monkeypatch.setattr(SqlCatalog, "search", search)
    response = catalog_client.get(path, params=params)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    search.assert_not_called()


def test_patient_schedules_query_params_match_contract(specs):
    contract, app = specs
    path = "/patients/{patient_id}/schedules"
    assert _query_params(contract["paths"][path]["get"]) == _query_params(app["paths"][path]["get"])
