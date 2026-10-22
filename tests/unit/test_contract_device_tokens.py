import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import CONTRACT, _request, _shape


@pytest.mark.parametrize(
    "method,operation", [("put", "registerMyDeviceToken"), ("delete", "unregisterMyDeviceToken")]
)
def test_token_operations_match_approved_contract(method, operation):
    contract, app = json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()
    expected = contract["paths"]["/me/device-tokens"][method]
    actual = app["paths"]["/me/device-tokens"][method]
    assert actual["operationId"] == expected["operationId"] == operation
    assert set(expected["responses"]) <= set(actual["responses"])
    assert _shape(contract, _request(contract, expected)) == _shape(app, _request(app, actual))
