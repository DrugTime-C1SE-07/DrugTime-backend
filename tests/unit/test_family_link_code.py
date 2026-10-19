"""Mã liên kết cố định (task 3.10, QD-04, QD-34): domain và use case."""

import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from drugtime.modules.family.application.get_link_code import MAX_ATTEMPTS, get_link_code
from drugtime.modules.family.domain import link_code
from drugtime.modules.family.domain.link_code import (
    ALPHABET,
    CODE_LENGTH,
    generate_code,
    qr_payload,
)
from drugtime.shared.errors import Forbidden, ServiceUnavailable

FAMILY_SRC = Path(link_code.__file__).resolve().parents[1]


class FakeLinkCodes:
    """stored: mã hiện có theo user; taken: mã đã thuộc user khác; racer: mã do request khác
    ghi xen vào ngay trước lần insert đầu tiên."""

    def __init__(self, stored=None, taken=(), racer=None):
        self.stored = dict(stored or {})
        self.taken = set(taken)
        self.racer = racer
        self.finds = 0
        self.inserts = []

    def find_by_patient(self, uow, patient_id):
        self.finds += 1
        return self.stored.get(patient_id)

    def insert_if_absent(self, uow, patient_id, code):
        self.inserts.append(code)
        if self.racer is not None:
            self.stored[patient_id], self.racer = self.racer, None
        if patient_id in self.stored:
            return self.stored[patient_id]
        if code in self.taken:
            return None
        self.stored[patient_id] = code
        return code


def _sequence(*codes):
    it = iter(codes)
    return lambda: next(it)


# --- domain -------------------------------------------------------------------------------


def test_alphabet_excludes_confusable_characters__AC4():
    assert len(ALPHABET) == len(set(ALPHABET)) == 31
    assert set(ALPHABET) == set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert not set("0O1IL") & set(ALPHABET)


def test_generate_code_length_and_alphabet__AC4():
    codes = [generate_code() for _ in range(10_000)]

    assert all(len(c) == CODE_LENGTH == 10 for c in codes)
    assert set("".join(codes)) <= set(ALPHABET)
    assert len(set(codes)) == len(codes)


def test_generate_code_uses_injected_choice__AC4():
    assert generate_code(choice=lambda alphabet: alphabet[0]) == "A" * 10


def test_generate_code_defaults_to_secrets_choice__AC4():
    assert generate_code.__defaults__ == (secrets.choice,)


def test_family_module_does_not_import_random__AC4():
    for path in FAMILY_SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "import random" not in source and "from random" not in source, path


def test_qr_payload_roundtrip__AC5():
    code = generate_code()
    url = urlparse(qr_payload(code))

    assert qr_payload(code) == f"drugtime://link?code={code}"
    assert url.scheme == "drugtime"
    assert parse_qs(url.query)["code"] == [code]


# --- use case -----------------------------------------------------------------------------


def test_creates_code_when_absent__AC1():
    user = uuid4()
    codes = FakeLinkCodes()

    result = get_link_code(
        None, user_id=user, is_admin=False, codes=codes, generate=_sequence("ABCDEFGHJK")
    )

    assert (result.patient_user_id, result.code) == (user, "ABCDEFGHJK")
    assert result.qr_payload == "drugtime://link?code=ABCDEFGHJK"
    assert codes.stored == {user: "ABCDEFGHJK"}


def test_returns_existing_code_without_insert__AC2():
    user = uuid4()
    codes = FakeLinkCodes(stored={user: "MNPQRSTUVW"})

    for _ in range(3):
        result = get_link_code(None, user_id=user, is_admin=False, codes=codes)
        assert result.code == "MNPQRSTUVW"
    assert codes.inserts == []


def test_returns_concurrent_winner_code__AC3():
    user = uuid4()
    codes = FakeLinkCodes(racer="WINNER2345")

    result = get_link_code(
        None, user_id=user, is_admin=False, codes=codes, generate=_sequence("LOSER23456")
    )

    assert result.code == "WINNER2345"
    assert codes.inserts == ["LOSER23456"]


def test_retries_on_code_collision__AC7():
    user = uuid4()
    codes = FakeLinkCodes(taken={"TAKEN23456"})

    result = get_link_code(
        None,
        user_id=user,
        is_admin=False,
        codes=codes,
        generate=_sequence("TAKEN23456", "FRESH23456"),
    )

    assert result.code == "FRESH23456"
    assert codes.inserts == ["TAKEN23456", "FRESH23456"]


def test_gives_up_after_max_attempts_503__AC7():
    user = uuid4()
    codes = FakeLinkCodes(taken={"TAKEN23456"})

    with pytest.raises(ServiceUnavailable) as exc:
        get_link_code(
            None, user_id=user, is_admin=False, codes=codes, generate=lambda: "TAKEN23456"
        )

    assert str(exc.value) == "link_code_unavailable"
    assert len(codes.inserts) == MAX_ATTEMPTS == 5
    assert codes.stored == {}


def test_admin_forbidden_before_any_query__AC9():
    codes = FakeLinkCodes()

    with pytest.raises(Forbidden) as exc:
        get_link_code(None, user_id=uuid4(), is_admin=True, codes=codes)

    assert str(exc.value) == "khong_co_quyen"
    assert codes.finds == 0 and codes.inserts == []


def test_errors_do_not_contain_code__AC10():
    codes = FakeLinkCodes(taken={"SECRET2345"})

    with pytest.raises(ServiceUnavailable) as exc:
        get_link_code(
            None, user_id=uuid4(), is_admin=False, codes=codes, generate=lambda: "SECRET2345"
        )

    assert "SECRET2345" not in str(exc.value)
