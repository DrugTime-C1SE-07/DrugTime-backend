"""Regression checks for constraints that operation shape parity alone cannot verify."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")

TARGET_OPERATIONS = (
    ("get", "/family/link-code"),
    ("post", "/admin/drug-interactions"),
    ("get", "/admin/drug-interactions"),
    ("get", "/admin/drug-interactions/{id}"),
    ("patch", "/admin/drug-interactions/{id}"),
    ("delete", "/admin/drug-interactions/{id}"),
    ("get", "/admin/drug-interactions/{id}/versions"),
    ("get", "/admin/drug-interaction-versions/{version_id}"),
    ("post", "/admin/drug-food-interactions"),
    ("get", "/admin/drug-food-interactions"),
    ("get", "/admin/drug-food-interactions/{id}"),
    ("patch", "/admin/drug-food-interactions/{id}"),
    ("delete", "/admin/drug-food-interactions/{id}"),
    ("get", "/admin/drug-food-interactions/{id}/versions"),
    ("get", "/admin/drug-food-interaction-versions/{version_id}"),
    ("get", "/admin/active-ingredients"),
    ("patch", "/medications/{id}"),
    ("post", "/medications/{id}/schedules"),
    ("patch", "/medications/{id}/schedules/{schedule_id}"),
    ("delete", "/medications/{id}/schedules/{schedule_id}"),
    ("get", "/patients/{patient_id}/schedules"),
    ("get", "/profile"),
    ("put", "/profile"),
    ("get", "/conditions"),
    ("post", "/profile/conditions"),
    ("patch", "/profile/conditions/{id}"),
    ("delete", "/profile/conditions/{id}"),
)


def _read_contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"Only local references are supported: {ref}")
        target: Any = spec
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


def _operation(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    return spec["paths"][path][method]


def _response_schema(spec: dict[str, Any], method: str, path: str, status: str) -> dict[str, Any]:
    response = _operation(spec, method, path)["responses"][status]
    return _resolve(spec, response["content"]["application/json"]["schema"])


def _audit_spec(spec: dict[str, Any]) -> set[str]:
    """Return audit finding codes; kept pure so broken fixtures test each guard."""
    findings: set[str] = set()
    schemas = spec.get("components", {}).get("schemas", {})

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if ref is not None:
                try:
                    _resolve(spec, {"$ref": ref})
                except (KeyError, ValueError):
                    findings.add("unresolved-ref")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(spec)

    operation_ids: list[str] = []
    for path_item in spec.get("paths", {}).values():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                operation_id = operation.get("operationId")
                if operation_id:
                    operation_ids.append(operation_id)
    if len(operation_ids) != len(set(operation_ids)):
        findings.add("duplicate-operation-id")

    if "bearerAuth" not in spec.get("components", {}).get("securitySchemes", {}):
        findings.add("missing-bearer-scheme")
    for method, path in TARGET_OPERATIONS:
        operation = spec.get("paths", {}).get(path, {}).get(method, {})
        schemes = {name for requirement in operation.get("security", []) for name in requirement}
        if "bearerAuth" not in schemes:
            findings.add("missing-bearer-security")

    envelope = schemas.get("ValidationError", {})
    detail = envelope.get("properties", {}).get("detail", {})
    item = detail.get("items", {})
    item_ref = item.get("$ref", "").rsplit("/", 1)[-1]
    item_schema = schemas.get(item_ref, {})
    if (
        "detail" not in envelope.get("required", [])
        or detail.get("type") != "array"
        or not {"loc", "msg", "type"}.issubset(item_schema.get("required", []))
    ):
        findings.add("validation-envelope-clobbered")
    return findings


def test_contract_audit_passes_and_detects_broken_contract_guards():
    contract = _read_contract()
    assert _audit_spec(contract) == set()

    broken_ref = copy.deepcopy(contract)
    broken_ref["components"]["schemas"]["BrokenFixture"] = {"$ref": "#/missing/Schema"}
    assert "unresolved-ref" in _audit_spec(broken_ref)

    duplicate_id = copy.deepcopy(contract)
    duplicate_id["paths"]["/profile"]["put"]["operationId"] = _operation(
        duplicate_id, "get", "/profile"
    )["operationId"]
    assert "duplicate-operation-id" in _audit_spec(duplicate_id)

    missing_security = copy.deepcopy(contract)
    del missing_security["paths"]["/profile"]["get"]["security"]
    assert "missing-bearer-security" in _audit_spec(missing_security)

    clobbered_envelope = copy.deepcopy(contract)
    clobbered_envelope["components"]["schemas"]["ValidationError"] = {
        "type": "object",
        "required": ["loc", "msg", "type"],
        "properties": {
            "loc": {"type": "array"},
            "msg": {"type": "string"},
            "type": {"type": "string"},
        },
    }
    assert "validation-envelope-clobbered" in _audit_spec(clobbered_envelope)


def test_link_code_contract_keeps_code_and_qr_constraints():
    contract = _read_contract()
    schema = _resolve(
        contract,
        _response_schema(contract, "get", "/family/link-code", "200"),
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"code", "qr_payload"}
    code = schema["properties"]["code"]
    assert code["pattern"] == r"^[A-HJKMNP-Z2-9]{10}$"
    assert (code["minLength"], code["maxLength"]) == (10, 10)
    qr = schema["properties"]["qr_payload"]
    assert qr["pattern"] == r"^drugtime://link\?code=[A-HJKMNP-Z2-9]{10}$"
    assert {"401", "403", "503"}.issubset(
        _operation(contract, "get", "/family/link-code")["responses"]
    )


def test_interaction_contract_keeps_composition_versions_scale_and_q1():
    contract = _read_contract()
    schemas = contract["components"]["schemas"]
    create = schemas["DrugInteractionCreate"]
    assert len(create["oneOf"]) == 2
    assert create["oneOf"][0]["required"] == ["ingredient_b_id"]
    assert create["oneOf"][1]["required"] == ["ingredient_b_external_name"]
    assert create["additionalProperties"] is False
    assert "verification_status" not in create["properties"]

    update = schemas["DrugInteractionUpdate"]
    assert update["minProperties"] == 2
    assert update["properties"]["expected_version"]["minimum"] == 1
    severity = schemas["InteractionSeverity"]
    assert (severity["minimum"], severity["maximum"]) == (1, 4)
    for label in (
        "cần theo dõi",
        "cần thận trọng",
        "cân nhắc lợi ích/nguy cơ",
        "phối hợp nguy hiểm",
    ):
        assert label in severity["description"]

    for path in ("/admin/drug-interactions", "/admin/drug-food-interactions"):
        description = _operation(contract, "post", path)["description"].lower()
        assert "hiệu lực ngay" in description
        assert "không có bước duyệt" in description
    assert "204" in _operation(contract, "delete", "/admin/drug-interactions/{id}")["responses"]
    assert (
        "content"
        not in _operation(contract, "delete", "/admin/drug-interactions/{id}")["responses"]["204"]
    )


def test_medication_schedule_contract_keeps_weekday_and_response_boundaries():
    contract = _read_contract()
    schemas = contract["components"]["schemas"]
    days = schemas["DaysOfWeek"]
    assert (days["minItems"], days["maxItems"], days["uniqueItems"]) == (1, 7, True)
    assert (days["items"]["minimum"], days["items"]["maximum"]) == (1, 7)
    update = schemas["UserMedicationUpdate"]
    assert "days_of_week" in update["properties"]
    assert "days_of_week" not in update.get("required", [])
    assert update["properties"]["days_of_week"]["$ref"] == "#/components/schemas/DaysOfWeek"

    delete_schedule = _operation(contract, "delete", "/medications/{id}/schedules/{schedule_id}")
    assert "200" in delete_schedule["responses"] and "204" not in delete_schedule["responses"]
    _response_schema(contract, "delete", "/medications/{id}/schedules/{schedule_id}", "200")
    patient_schedules = _operation(contract, "get", "/patients/{patient_id}/schedules")
    query = {
        param["name"]: param["schema"]
        for param in patient_schedules["parameters"]
        if param["in"] == "query"
    }
    assert (query["limit"]["default"], query["limit"]["minimum"], query["limit"]["maximum"]) == (
        100,
        1,
        200,
    )
    assert (query["cursor"]["minLength"], query["cursor"]["maxLength"]) == (1, 200)
    page = schemas["PatientScheduleList"]
    assert page["properties"]["next_cursor"]["type"] == ["string", "null"]


def test_profile_condition_contract_keeps_self_only_no_store_and_error_semantics():
    contract = _read_contract()
    schemas = contract["components"]["schemas"]
    profile_get = _operation(contract, "get", "/profile")
    cache_control = profile_get["responses"]["200"]["headers"]["Cache-Control"]["schema"]
    assert cache_control.get("const", cache_control.get("enum")) in ("no-store", ["no-store"])
    profile = schemas["HealthProfileResponse"]
    assert set(profile["required"]) == {"full_name", "date_of_birth", "gender", "conditions"}
    for name in ("full_name", "date_of_birth", "gender"):
        assert profile["properties"][name]["anyOf"][-1]["type"] == "null"

    profile_update = schemas["ProfileUpdateRequest"]
    assert set(profile_update["required"]) == {"full_name", "date_of_birth", "gender"}
    assert profile_update["additionalProperties"] is False
    assert "content" not in _operation(contract, "put", "/profile")["responses"]["204"]

    condition_patch = _operation(contract, "patch", "/profile/conditions/{id}")
    assert "404" in condition_patch["responses"] and "403" in condition_patch["responses"]
    assert "404" in condition_patch["description"]
    assert "user_condition_not_found" in condition_patch["description"]
    assert "consent_revoked" in condition_patch["description"]
    condition_delete = _operation(contract, "delete", "/profile/conditions/{id}")
    assert "404" in condition_delete["responses"] and "403" in condition_delete["responses"]
    assert "content" not in condition_delete["responses"]["204"]
