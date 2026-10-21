"""Contract approved của GET /adherence; không sửa contract để khớp implementation."""

import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound.history_schemas import AdherenceHistoryResponse

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "api_contract/openapi.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
OPERATION = CONTRACT["paths"]["/adherence"]["get"]
EXAMPLES = OPERATION["responses"]["200"]["content"]["application/json"]["examples"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_all_12_contract_examples_validate_and_keep_json_number_and_precision(name):
    payload = EXAMPLES[name]["value"]
    result = AdherenceHistoryResponse.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert result == payload
    rate = result["summary"]["adherence_rate"]
    assert rate is None or isinstance(rate, (float, int))


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
    payload = copy.deepcopy(EXAMPLES["byDate"]["value"])
    payload["groups"][0]["doses"][0].update(change)
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def test_reject_recorded_pending_even_without_taken_at():
    payload = copy.deepcopy(EXAMPLES["pending"]["value"])
    payload["groups"][0]["doses"][0]["status_source"] = "recorded"
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


def test_exact_bigint_maximum_is_accepted_without_rounding():
    payload = copy.deepcopy(EXAMPLES["byDate"]["value"])
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
    payload = copy.deepcopy(EXAMPLES["empty"]["value"])
    payload["summary"].update(change)
    with pytest.raises(ValidationError):
        AdherenceHistoryResponse.model_validate(payload)


@pytest.fixture(scope="module")
def generated():
    return create_app().openapi()


def resolve(spec, node):
    while "$ref" in node:
        node = spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
    return node


def canonical(spec, node):
    if isinstance(node, list):
        return [canonical(spec, item) for item in node]
    if not isinstance(node, dict):
        return node
    node = resolve(spec, node)
    result = {
        key: sorted(value) if key == "required" else canonical(spec, value)
        for key, value in node.items()
        if key not in {"title", "description", "example", "examples"}
    }
    if result.get("type") == "integer" and "exclusiveMaximum" in result:
        result["maximum"] = math.ceil(result.pop("exclusiveMaximum")) - 1
    return result


@pytest.mark.parametrize(
    "name", [name for name in CONTRACT["components"]["schemas"] if name.startswith("Adherence")]
)
def test_generated_response_shapes_required_nullable_enums_and_constraints(generated, name):
    assert canonical(CONTRACT, CONTRACT["components"]["schemas"][name]) == canonical(
        generated, generated["components"]["schemas"][name]
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
    assert canonical(CONTRACT, expected_response) == canonical(generated, actual_response)
