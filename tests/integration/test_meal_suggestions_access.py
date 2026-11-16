"""Phân quyền POST /patients/{patient_id}/meal-suggestions (task 4.26: AC14, AC15, AC16).

Bộ cross-patient của wf-health-endpoint: mỗi ca kiểm response, access_logs và số lần gọi LLM.
Chỉ chính chủ có consent ai_meal được gọi (Action.WRITE); người thân luôn bị từ chối ở 4.26.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_meal_suggestions_api import (
    BODY,
    create_patient,
    disable_real_llm,
    install_fake_llm,
    log,
    meal_rows,
    suggest,
)

from drugtime.shared.config import get_settings


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Không phụ thuộc .env máy dev; không bao giờ gọi Anthropic thật."""
    disable_real_llm(monkeypatch)
    yield
    get_settings.cache_clear()


@pytest.fixture
def llm(client):
    return install_fake_llm(client)


@pytest.fixture
def patient(client, db, make, auth, admin_auth, scheduled_body):
    return create_patient(client, db, make, auth, admin_auth, scheduled_body)


def test_self_allowed_logged(client, db, make, auth, llm, patient):
    p = patient["id"]
    r = suggest(client, auth, p, p)
    assert r.status_code == 200, r.text
    assert make.access_logs(p) == [log(p, "patient", "allowed")]
    assert len(llm.prompts) == 1 and len(meal_rows(db, p)) == 1


def _caller(case, make, p):
    if case == "family_with_full_consent":
        make.consent(p, "family_sharing")  # đủ điều kiện chia sẻ để đọc; vẫn không được ghi
        family = make.user(consents=("health_data", "ai_meal"))
        make.link(p, family)
        return family, "family"
    if case == "family_without_link":
        return make.user(consents=("health_data", "ai_meal")), "khong_co_quyen"
    if case == "admin":
        return make.user(admin=True), "admin"
    if case == "other_patient":
        return make.user(consents=("health_data", "ai_meal")), "khong_co_quyen"
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case", ["family_with_full_consent", "family_without_link", "admin", "other_patient"]
)
def test_cross_patient_denied__AC14(client, db, make, auth, llm, patient, case):
    p = patient["id"]
    caller, role = _caller(case, make, p)
    r = suggest(client, auth, caller, p)
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert patient["condition"] not in r.text and patient["ingredient"] not in r.text
    assert make.access_logs(p) == [log(caller, role, "denied", "khong_co_quyen")]
    assert llm.prompts == [] and meal_rows(db, p) == []
    if case == "other_patient":
        assert make.access_logs(caller) == [] and meal_rows(db, caller) == []


@pytest.mark.parametrize(
    "case", ["family_with_full_consent", "family_without_link", "admin", "other_patient"]
)
def test_cross_patient_refresh_denied_before_previous_lookup__5_11_AC17(
    client, db, make, auth, llm, patient, case
):
    """Có previous_suggestion_id (của chính P) vẫn bị PEP chặn trước khi đọc gợi ý trước."""
    p = patient["id"]
    first = suggest(client, auth, p, p)
    assert first.status_code == 200, first.text
    previous_id = first.json()["suggestion_id"]
    caller, role = _caller(case, make, p)
    r = suggest(client, auth, caller, p, body={**BODY, "previous_suggestion_id": previous_id})
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert make.access_logs(p)[-1] == log(caller, role, "denied", "khong_co_quyen")
    assert len(llm.prompts) == 1 and len(meal_rows(db, p)) == 1  # chỉ lần gợi ý đầu của P


def test_refresh_after_consent_revoked_denied__5_11_AC17(client, db, make, auth, llm, patient):
    p = patient["id"]
    previous_id = suggest(client, auth, p, p).json()["suggestion_id"]
    make.revoke_consent(p, "ai_meal")
    r = suggest(client, auth, p, p, body={**BODY, "previous_suggestion_id": previous_id})
    assert (r.status_code, r.json()) == (403, {"detail": "consent_revoked"})
    assert len(llm.prompts) == 1 and len(meal_rows(db, p)) == 1


def test_unknown_patient_403_no_log(client, make, auth, llm):
    caller = make.user(consents=("health_data", "ai_meal"))
    unknown = uuid4()
    r = suggest(client, auth, caller, unknown)
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert make.access_logs(unknown) == [] and llm.prompts == []


def test_no_ai_meal_consent__AC15(client, db, make, auth, llm):
    p = make.user(consents=("health_data",))
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (403, {"detail": "consent_revoked"})
    assert make.access_logs(p) == [log(p, "patient", "denied", "consent_revoked")]
    assert llm.prompts == [] and meal_rows(db, p) == []


def test_revoke_consent_effective_next_request__AC15(client, db, make, auth, llm, patient):
    p = patient["id"]
    assert suggest(client, auth, p, p).status_code == 200
    make.revoke_consent(p, "ai_meal")
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (403, {"detail": "consent_revoked"})
    assert make.access_logs(p) == [
        log(p, "patient", "allowed"),
        log(p, "patient", "denied", "consent_revoked"),
    ]
    assert len(llm.prompts) == 1 and len(meal_rows(db, p)) == 1


def test_family_link_revoked_still_denied(client, db, make, auth, llm, patient):
    """Hủy liên kết không mở quyền nào: trước và sau đều 403."""
    p = patient["id"]
    make.consent(p, "family_sharing")
    family = make.user(consents=("health_data", "ai_meal"))
    link_id = make.link(p, family)
    assert suggest(client, auth, family, p).status_code == 403
    db.execute(text("UPDATE caregiver_links SET status = 'revoked', revoked_at = now() "
                    "WHERE id = :i"), {"i": link_id})
    r = suggest(client, auth, family, p)
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert [row["result"] for row in make.access_logs(p)] == ["denied", "denied"]
    assert llm.prompts == []


def test_pending_deletion_denied__AC16(client, db, make, auth, llm, patient):
    p = patient["id"]
    db.execute(
        text("INSERT INTO data_deletion_requests (user_id, status, requested_at, "
             "scheduled_deletion_at) "
             "VALUES (:u, 'cho_duyet', now(), now() + interval '720 hours')"),
        {"u": p},
    )
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert make.access_logs(p) == [log(p, "patient", "denied", "khong_co_quyen")]
    assert llm.prompts == [] and meal_rows(db, p) == []
