import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_family_links import canonical
from tests.unit.test_contract_medication import CONTRACT, _response, _shape

OPERATIONS = [
    ("get", "/family/caregivers", "listMyCaregivers"),
    ("patch", "/family/links/{link_id}/sharing", "updateFamilyLinkSharing"),
    ("post", "/family/links/{link_id}/revoke", "revokeFamilyLink"),
]
SCHEMAS = ["Caregiver", "CaregiverList", "FamilyLinkSharingUpdate", "FamilyLinkRevocation"]


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


@pytest.mark.parametrize("name", SCHEMAS)
def test_caregiver_schemas_match_contract__AC1(specs, name):
    contract, app = specs
    assert canonical(contract, contract["components"]["schemas"][name]) == canonical(
        app, app["components"]["schemas"][name]
    )


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
def test_caregiver_operations_match_contract__AC1(specs, method, path, operation):
    contract, app = specs
    c, a = contract["paths"][path][method], app["paths"][path][method]
    assert c["operationId"] == a["operationId"] == operation
    assert set(c["responses"]) == set(a["responses"])
    assert _shape(contract, _response(contract, c, "200")) == _shape(app, _response(app, a, "200"))
    assert ("requestBody" in c) is ("requestBody" in a)
    cp = [p for p in c.get("parameters", []) if p["in"] != "header"]
    ap = [p for p in a.get("parameters", []) if p["in"] != "header"]
    assert {(p["name"], p["in"], p["required"]) for p in cp} == {
        (p["name"], p["in"], p["required"]) for p in ap
    }
    for cparam in cp:
        aparam = next(p for p in ap if p["name"] == cparam["name"])
        assert canonical(contract, cparam["schema"]) == canonical(app, aparam["schema"])
    if "requestBody" in c:
        assert a["requestBody"]["required"] is True
        assert canonical(
            contract, c["requestBody"]["content"]["application/json"]["schema"]
        ) == canonical(app, a["requestBody"]["content"]["application/json"]["schema"])
