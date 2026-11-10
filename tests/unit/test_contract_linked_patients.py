import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_family_links import canonical
from tests.unit.test_contract_medication import CONTRACT


def normalized(schema):
    """OpenAPI 3.1 permits either a type array or anyOf for a simple nullable/union type."""
    if isinstance(schema, dict):
        result = {key: normalized(value) for key, value in schema.items()}
        if isinstance(result.get("type"), list):
            types = result.pop("type")
            result["anyOf"] = [{"type": t} for t in types]
        return result
    if isinstance(schema, list):
        return [normalized(item) for item in schema]
    return schema


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


@pytest.mark.parametrize("name", ["LinkedPatient", "LinkedPatientList"])
def test_patient_schemas_match_contract(specs, name):
    contract, generated = specs
    assert canonical(contract, contract["components"]["schemas"][name]) == canonical(
        generated, generated["components"]["schemas"][name]
    )


def test_generated_operation_matches_contract(specs):
    contract, generated = specs
    c = contract["paths"]["/family/patients"]["get"]
    g = generated["paths"]["/family/patients"]["get"]
    for key in ("operationId", "security", "tags", "x-health-scope", "x-health-audit-self"):
        assert c[key] == g[key]
    assert set(c["responses"]) == set(g["responses"])
    assert "requestBody" not in g
    assert not [p for p in g.get("parameters", []) if p["in"] != "header"]
    for code, response in c["responses"].items():
        assert g["responses"][code]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
        actual = g["responses"][code]["content"]["application/json"]["schema"]
        expected = response["content"]["application/json"]["schema"]
        assert normalized(canonical(contract, expected)) == normalized(canonical(generated, actual))
