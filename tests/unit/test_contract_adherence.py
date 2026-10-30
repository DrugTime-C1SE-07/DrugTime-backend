"""Contract approved của GET /adherence; không sửa contract để khớp implementation."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from drugtime.modules.adherence.adapters.inbound.history_schemas import (
    AdherenceDose,
    AdherenceHistoryResponse,
    AdherenceSummary,
)

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "api_contract/openapi.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
OPERATION = CONTRACT["paths"]["/adherence"]["get"]
EXAMPLES = OPERATION["responses"]["200"]["content"]["application/json"]["examples"]
DATE_EXAMPLE = EXAMPLES["family_by_date"]["value"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_contract_examples_validate_and_keep_json_number_and_precision(name):
    payload = EXAMPLES[name]["value"]
    result = AdherenceHistoryResponse.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert result == payload
    rate = result["summary"]["adherence_rate"]
    assert rate is None or isinstance(rate, (float, int))


def pending_payload():
    payload = copy.deepcopy(DATE_EXAMPLE)
    dose = payload["groups"][0]["doses"][0]
    dose.update(taken_at=None, status="cho_xac_nhan", status_source="inferred")
    for summary in (payload["summary"], payload["groups"][0]["summary"]):
        summary.update(taken=0, pending=1, counted=0, adherence_rate=None)
    return payload


def empty_payload():
    payload = copy.deepcopy(DATE_EXAMPLE)
    payload["groups"] = []
    payload["summary"].update(total=0, taken=0, counted=0, adherence_rate=None)
    return payload


def medication_payload():
    payload = copy.deepcopy(DATE_EXAMPLE)
    payload["group_by"] = "medication"
    group = payload["groups"][0]
    group.pop("date")
    group["medication_id"] = group["doses"][0]["medication_id"]
    group["medication_name"] = group["doses"][0]["medication_name"]
    return payload


def test_pending_empty_and_medication_variants_validate_on_wire():
    for payload in (pending_payload(), empty_payload(), medication_payload()):
        result = AdherenceHistoryResponse.model_validate(payload).model_dump(
            mode="json", by_alias=True
        )
        assert result == payload
        assert result["summary"]["adherence_rate"] is None or isinstance(
            result["summary"]["adherence_rate"], (float, int)
        )


@pytest.mark.parametrize(
    "change",
    [
        {"taken_at": None},
        {"status_source": "inferred"},
        {"status": "cho_xac_nhan"},
        {"status": "bo_lo"},
        {"schedule_id": 0},
        {"schedule_id": 9223372036854775808},
        {"unexpected": True},
        {"scheduled_at": "2026-10-19T08:00:00"},
    ],
)
def test_reject_invalid_dose_status_source_timestamp_and_constraints(change):
    payload = copy.deepcopy(DATE_EXAMPLE)
    payload["groups"][0]["doses"][0].update(change)
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def unverified_payload():
    payload = copy.deepcopy(DATE_EXAMPLE)
    dose = payload["groups"][0]["doses"][0]
    dose.update(taken_at=None, status="chua_xac_minh", status_source="inferred")
    for summary in (payload["summary"], payload["groups"][0]["summary"]):
        summary.update(taken=0, unverified=1, counted=0, adherence_rate=None)
    payload["patient_last_synced_at"] = None
    return payload


def test_unverified_variant_validates_on_wire__AC40_AC41():
    payload = unverified_payload()
    result = AdherenceHistoryResponse.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert result == payload


@pytest.mark.parametrize(
    "change",
    [
        {"taken_at": "2026-10-19T08:05:00+07:00"},
        {"status_source": "recorded"},
    ],
)
def test_reject_unverified_with_taken_at_or_recorded__AC41(change):
    payload = unverified_payload()
    payload["groups"][0]["doses"][0].update(change)
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def test_unverified_counts_in_total_and_last_synced_is_required__AC41():
    payload = unverified_payload()
    payload["summary"]["unverified"] = 0
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)
    payload = unverified_payload()
    del payload["patient_last_synced_at"]
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def test_last_synced_is_rendered_in_vietnam_time__AC41():
    payload = unverified_payload()
    payload["patient_last_synced_at"] = "2026-10-19T01:00:00Z"
    result = AdherenceHistoryResponse.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert result["patient_last_synced_at"] == "2026-10-19T08:00:00+07:00"


def test_reject_recorded_pending_even_without_taken_at():
    payload = pending_payload()
    payload["groups"][0]["doses"][0]["status_source"] = "recorded"
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def test_exact_bigint_maximum_is_accepted_without_rounding():
    payload = copy.deepcopy(DATE_EXAMPLE)
    payload["groups"][0]["doses"][0]["schedule_id"] = 9223372036854775807
    result = AdherenceHistoryResponse.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert result["groups"][0]["doses"][0]["schedule_id"] == 9223372036854775807


@pytest.mark.parametrize(
    "change",
    [
        {"adherence_rate": 0},
        {"adherence_rate": -1},
        {"total": -1},
        {"counted": 1},
        {"adherence_rate": "bad"},
        {"unexpected": True},
    ],
)
def test_reject_invalid_empty_summary_or_null_rate(change):
    payload = empty_payload()
    payload["summary"].update(change)
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


@pytest.fixture(scope="module")
def generated():
    from drugtime.main import create_app

    return create_app().openapi()


def resolve(spec, node):
    while "$ref" in node:
        node = spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
    return node


def schema_types(node):
    if "anyOf" in node:
        return {branch["type"] for branch in node["anyOf"]}
    value = node["type"]
    return set(value) if isinstance(value, list) else {value}


def test_response_required_nullable_enums_and_constraints():
    schemas = CONTRACT["components"]["schemas"]
    for name, model in (("AdherenceDose", AdherenceDose), ("AdherenceSummary", AdherenceSummary)):
        expected, actual = schemas[name], model.model_json_schema()
        assert set(actual["required"]) == set(expected["required"])
        assert actual["additionalProperties"] is expected["additionalProperties"] is False
        assert actual["allOf"]  # Conditional dose/rate rules are also exercised on wire above.

    dose = AdherenceDose.model_json_schema()["properties"]
    expected_dose = schemas["AdherenceDose"]["properties"]
    for field in ("medication_id", "schedule_id"):
        for key in ("type", "format", "minimum", "exclusiveMaximum"):
            assert dose[field][key] == expected_dose[field][key]
    for field in ("status", "status_source"):
        assert set(dose[field]["enum"]) == set(expected_dose[field]["enum"])
    assert schema_types(dose["taken_at"]) == schema_types(expected_dose["taken_at"])

    summary = AdherenceSummary.model_json_schema()["properties"]
    expected_summary = schemas["AdherenceSummary"]["properties"]
    for field in ("total", "taken", "late", "missed", "pending", "unverified", "counted"):
        assert summary[field]["minimum"] == expected_summary[field]["minimum"] == 0
    assert schema_types(summary["adherence_rate"]) == schema_types(
        expected_summary["adherence_rate"]
    )
    rate = next(
        branch for branch in summary["adherence_rate"]["anyOf"] if branch["type"] == "number"
    )
    for key in ("minimum", "maximum", "multipleOf"):
        assert rate[key] == expected_summary["adherence_rate"][key]

    root = AdherenceHistoryResponse.model_json_schema()
    expected_root = schemas["AdherenceHistoryResponse"]
    assert set(root["discriminator"]["mapping"]) == set(expected_root["discriminator"]["mapping"])
    for name in ("AdherenceDateGroup", "AdherenceMedicationGroup"):
        assert (
            root["$defs"][name]["properties"]["doses"]["minItems"]
            == schemas[name]["properties"]["doses"]["minItems"]
        )


def test_contract_query_security_status_headers(generated):
    op = generated["paths"]["/adherence"]["get"]
    assert op["operationId"] == OPERATION["operationId"]
    assert op["security"] == OPERATION["security"]
    assert set(op["responses"]) == set(OPERATION["responses"])
    assert "requestBody" not in op
    query = {p["name"]: p for p in op["parameters"] if p["in"] == "query"}
    assert set(query) == {p["name"] for p in OPERATION["parameters"]}
    for expected in OPERATION["parameters"]:
        actual = query[expected["name"]]
        assert not actual.get("required", False)
        schema = resolve(generated, actual["schema"])
        # Optional query arguments can be omitted; null is not an encoded query value.
        if "anyOf" in schema:
            schema = next(branch for branch in schema["anyOf"] if branch.get("type") != "null")
        schema = resolve(generated, schema)
        for key, value in expected["schema"].items():
            assert schema.get(key, actual["schema"].get(key)) == value
    for code in OPERATION["responses"]:
        actual = op["responses"][code]
        assert actual["headers"]["Cache-Control"]["schema"] == {
            "type": "string",
            "const": "no-store",
        }
        assert "application/json" in actual["content"]
    actual_response = op["responses"]["200"]["content"]["application/json"]["schema"]
    expected_response = OPERATION["responses"]["200"]["content"]["application/json"]["schema"]
    assert actual_response["$ref"].rsplit("/", 1)[1] == expected_response["$ref"].rsplit("/", 1)[1]
