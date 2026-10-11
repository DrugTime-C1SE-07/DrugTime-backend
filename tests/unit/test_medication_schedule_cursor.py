import base64
import json
from uuid import uuid4

import pytest

from drugtime.modules.medication.domain.schedule_cursor import decode, encode
from drugtime.shared.errors import DomainError

P = uuid4()


def _raw(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_roundtrip():
    for last_id in (0, 1, 302, 2**62):
        assert decode(encode(P, last_id), P) == last_id


def test_cursor_is_url_safe_without_padding():
    c = encode(P, 302)
    assert "=" not in c and "+" not in c and "/" not in c


@pytest.mark.parametrize(
    "cursor",
    [
        "x",
        "!!!",
        "abc",  # base64 hợp lệ nhưng không phải JSON
        _raw([1, 2]),
        _raw({"p": str(P)}),
        _raw({"a": 5}),
        _raw({"p": "not-a-uuid", "a": 5}),
        _raw({"p": str(P), "a": "5"}),
        _raw({"p": str(P), "a": True}),
        _raw({"p": str(P), "a": -1}),
        _raw({"p": str(P), "a": 1.5}),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_garbage_is_invalid_cursor(cursor):
    with pytest.raises(DomainError, match="^invalid_cursor$"):
        decode(cursor, P)


def test_cursor_of_other_patient_is_invalid():
    with pytest.raises(DomainError, match="^invalid_cursor$"):
        decode(encode(uuid4(), 5), P)
