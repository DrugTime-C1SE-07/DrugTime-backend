"""Quản lý người giám sát phía patient (adhoc-20261020-family-link-approval).

GET /family/caregivers, PATCH /family/links/{link_id}/sharing, POST /family/links/{link_id}/revoke.
Chạy trên Postgres thật với api_role và phiên đăng nhập thật. Bao phủ AC3, AC5, AC10–AC13.
"""

from uuid import uuid4

import pytest

CAREGIVERS = "/family/caregivers"
VERSION = "2026-10-v1"
CAREGIVER_KEYS = {
    "link_id",
    "family_user_id",
    "family_full_name",
    "status",
    "sharing_enabled",
    "approved_at",
}


def _sharing(link_id: int) -> str:
    return f"/family/links/{link_id}/sharing"


def _revoke(link_id: int) -> str:
    return f"/family/links/{link_id}/revoke"


def _approve(client, auth, patient, family, link_id):
    r = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": VERSION,
        },
        headers=auth(patient),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _approved_link(client, make, auth, patient=None, *, sharing=False):
    """Liên kết active đi qua approve thật (có bằng chứng); bật chia sẻ qua PATCH nếu cần."""
    patient = patient or make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link_id = make.pending_link(patient, family)
    _approve(client, auth, patient, family, link_id)
    if sharing:
        r = client.patch(_sharing(link_id), json={"sharing_enabled": True}, headers=auth(patient))
        assert r.status_code == 200, r.text
    return patient, family, link_id


def _operations(make, actor):
    return [
        (a["operation"], a["result"], a["reason"]) for a in make.family_audit_events(actor_id=actor)
    ]


# --- Danh sách người giám sát (AC11, AC3) ------------------------------------------------------


def test_list_only_own_active_ordered_minimal__AC11(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    _, first, first_link = _approved_link(client, make, auth, patient, sharing=True)
    _, second, second_link = _approved_link(client, make, auth, patient)
    legacy = make.user()
    legacy_link = make.link(patient, legacy, status="active", legacy=True, sharing=False)
    make.pending_link(patient, make.user())
    make.link(patient, make.user(), status="rejected", sharing=False)
    make.link(patient, make.user(), status="revoked")
    _approved_link(client, make, auth)  # liên kết của patient khác

    r = client.get(CAREGIVERS, headers=auth(patient))

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # Chấp thuận sau xếp trước; liên kết cũ không có bằng chứng (approved_at null) xếp cuối.
    assert [i["link_id"] for i in items] == [second_link, first_link, legacy_link]
    assert all(set(i) == CAREGIVER_KEYS and i["status"] == "active" for i in items)
    by_id = {i["link_id"]: i for i in items}
    assert by_id[first_link]["family_user_id"] == str(first)
    assert by_id[first_link]["sharing_enabled"] is True
    assert by_id[second_link]["sharing_enabled"] is False
    assert by_id[first_link]["family_full_name"] == "Test User"
    assert by_id[first_link]["approved_at"] is not None
    assert by_id[legacy_link]["approved_at"] is None
    assert by_id[second_link]["family_user_id"] == str(second)

    listing = [
        a for a in make.family_audit_events(actor_id=patient) if a["operation"] == "list_caregivers"
    ]
    assert [(a["result"], a["patient_user_id"], a["link_id"]) for a in listing] == [
        ("allowed", patient, None)
    ]


def test_empty_list_returns_items_empty__AC11(client, make, auth):
    r = client.get(CAREGIVERS, headers=auth(make.user()))
    assert r.status_code == 200 and r.json() == {"items": []}


def test_approved_link_moves_from_pending_to_caregivers__AC3(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link_id = make.pending_link(patient, family)
    pending = client.get("/family/links?status=pending", headers=auth(patient)).json()["items"]
    assert [p["link_id"] for p in pending] == [link_id]

    approval = _approve(client, auth, patient, family, link_id)

    assert approval["sharing_enabled"] is False
    assert client.get("/family/links?status=pending", headers=auth(patient)).json()["items"] == []
    items = client.get(CAREGIVERS, headers=auth(patient)).json()["items"]
    assert [(i["link_id"], i["sharing_enabled"]) for i in items] == [(link_id, False)]
    assert items[0]["approved_at"] is not None


def test_caregivers_rejects_query_parameters__AC11(client, make, auth):
    r = client.get(CAREGIVERS + "?patient_id=" + str(uuid4()), headers=auth(make.user()))
    assert r.status_code == 422


# --- Bật/tắt chia sẻ (AC12, AC10, AC7) ---------------------------------------------------------


def test_enable_disable_idempotent_and_audit__AC12(client, make, auth):
    patient, _, link_id = _approved_link(client, make, auth)

    on = client.patch(_sharing(link_id), json={"sharing_enabled": True}, headers=auth(patient))
    assert on.status_code == 200, on.text
    assert set(on.json()) == CAREGIVER_KEYS
    assert on.json()["sharing_enabled"] is True and on.json()["approved_at"] is not None
    assert make.link_row(link_id)["sharing_enabled"] is True

    again = client.patch(_sharing(link_id), json={"sharing_enabled": True}, headers=auth(patient))
    assert again.status_code == 200 and again.json() == on.json()

    off = client.patch(_sharing(link_id), json={"sharing_enabled": False}, headers=auth(patient))
    assert off.status_code == 200 and off.json()["sharing_enabled"] is False
    assert make.link_row(link_id)["sharing_enabled"] is False
    assert make.link_row(link_id)["status"] == "active"

    sharing_ops = [op for op in _operations(make, patient) if "sharing" in op[0]]
    assert sharing_ops == [
        ("enable_sharing", "allowed", None),
        ("enable_sharing", "allowed", None),
        ("disable_sharing", "allowed", None),
    ]


def test_disable_allowed_without_consent__AC12(client, make, auth):
    patient, _, link_id = _approved_link(client, make, auth, sharing=True)
    make.revoke_consent(patient, "family_sharing")

    r = client.patch(_sharing(link_id), json={"sharing_enabled": False}, headers=auth(patient))

    assert r.status_code == 200 and r.json()["sharing_enabled"] is False
    assert make.link_row(link_id)["sharing_enabled"] is False


def test_enable_without_consent_403_denied_audit__AC7_AC10(client, make, auth):
    patient, _, link_id = _approved_link(client, make, auth)
    make.revoke_consent(patient, "family_sharing")

    r = client.patch(_sharing(link_id), json={"sharing_enabled": True}, headers=auth(patient))

    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert make.link_row(link_id)["sharing_enabled"] is False
    denied = [a for a in make.family_audit_events(actor_id=patient) if a["result"] == "denied"]
    assert [(a["operation"], a["reason"], a["link_id"]) for a in denied] == [
        ("enable_sharing", "consent_revoked", link_id)
    ]


def test_enable_legacy_link_409_confirmation_missing_but_disable_ok__AC10(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    link_id = make.link(patient, make.user(), status="active", legacy=True, sharing=True)

    r = client.patch(_sharing(link_id), json={"sharing_enabled": True}, headers=auth(patient))
    assert r.status_code == 409 and r.json() == {"detail": "consent_confirmation_missing"}

    off = client.patch(_sharing(link_id), json={"sharing_enabled": False}, headers=auth(patient))
    assert off.status_code == 200 and off.json()["approved_at"] is None
    assert make.link_row(link_id)["sharing_enabled"] is False


@pytest.mark.parametrize("status", ["pending", "rejected", "revoked"])
@pytest.mark.parametrize("enabled", [True, False])
def test_sharing_on_non_active_link_409__AC10(client, make, auth, status, enabled):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    if status == "pending":
        link_id = make.pending_link(patient, family)
    else:
        link_id = make.link(patient, family, status=status, sharing=False)
    before = make.link_row(link_id)

    r = client.patch(_sharing(link_id), json={"sharing_enabled": enabled}, headers=auth(patient))

    assert r.status_code == 409 and r.json() == {"detail": "family_link_not_active"}
    assert make.link_row(link_id) == before


# --- Hủy liên kết (AC13, AC10) -----------------------------------------------------------------


def test_revoke_keeps_history_and_replay_returns_same_time__AC13(client, make, auth):
    patient, family, link_id = _approved_link(client, make, auth, sharing=True)

    first = client.post(_revoke(link_id), headers=auth(patient))

    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"link_id", "family_user_id", "status", "revoked_at"}
    assert (body["link_id"], body["family_user_id"], body["status"]) == (
        link_id,
        str(family),
        "revoked",
    )
    row = make.link_row(link_id)
    assert row["status"] == "revoked" and row["revoked_at"] is not None
    assert len(make.consent_confirmations(link_id)) == 1  # bằng chứng giữ nguyên (QD-30)

    again = client.post(_revoke(link_id), headers=auth(patient))
    assert again.status_code == 200 and again.json() == body
    assert make.link_row(link_id)["revoked_at"] == row["revoked_at"]
    revokes = [op for op in _operations(make, patient) if op[0] == "revoke"]
    assert revokes == [("revoke", "allowed", None)] * 2
    assert client.get(CAREGIVERS, headers=auth(patient)).json()["items"] == []


def test_relink_after_revoke_starts_unshared_with_new_evidence__AC13(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    code = client.get("/family/link-code", headers=auth(patient)).json()["code"]

    def send():
        return client.post(
            "/family/link-requests",
            json={"client_uuid": str(uuid4()), "code": code},
            headers=auth(family),
        )

    first = send()
    assert first.status_code == 201, first.text
    old_link = first.json()["id"]
    _approve(client, auth, patient, family, old_link)
    client.patch(_sharing(old_link), json={"sharing_enabled": True}, headers=auth(patient))
    assert client.post(_revoke(old_link), headers=auth(patient)).status_code == 200

    second = send()

    assert second.status_code == 201, second.text
    new_link = second.json()["id"]
    assert new_link != old_link and second.json()["status"] == "pending"
    approval = _approve(client, auth, patient, family, new_link)
    assert approval["sharing_enabled"] is False  # không khôi phục chia sẻ cũ
    assert len(make.consent_confirmations(new_link)) == 1
    assert len(make.consent_confirmations(old_link)) == 1
    assert make.link_row(old_link)["status"] == "revoked"
    items = client.get(CAREGIVERS, headers=auth(patient)).json()["items"]
    assert [(i["link_id"], i["sharing_enabled"]) for i in items] == [(new_link, False)]


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_revoke_pending_or_rejected_409__AC10(client, make, auth, status):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    if status == "pending":
        link_id = make.pending_link(patient, family)
    else:
        link_id = make.link(patient, family, status="rejected", sharing=False)
    before = make.link_row(link_id)

    r = client.post(_revoke(link_id), headers=auth(patient))

    assert r.status_code == 409 and r.json() == {"detail": "invalid_link_transition"}
    assert make.link_row(link_id) == before


def test_revoke_with_body_is_422__AC10(client, make, auth):
    patient, _, link_id = _approved_link(client, make, auth)
    r = client.post(_revoke(link_id), content=b"{}", headers=auth(patient))
    assert r.status_code == 422
    assert make.link_row(link_id)["status"] == "active"


def test_missing_link_404_without_allowed_audit__AC10(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    missing = 2_000_000_000

    patch = client.patch(_sharing(missing), json={"sharing_enabled": True}, headers=auth(patient))
    revoke = client.post(_revoke(missing), headers=auth(patient))

    for r in (patch, revoke):
        assert r.status_code == 404 and r.json() == {"detail": "family_link_not_found"}
    assert make.family_audit_events(actor_id=patient) == []


# --- Chỉ đúng patient (AC5) --------------------------------------------------------------------


def test_new_endpoints_denied_caller_matrix__AC5(client, make, auth, admin_auth):
    """Người thân của link, người lạ và admin: PATCH và revoke → 403, không đổi gì, mỗi lượt
    một audit denied với actor là người gọi. Admin không xem được danh sách; người khác chỉ thấy
    liên kết của chính mình. Cặp allowed: patient làm được."""
    patient, family, link_id = _approved_link(client, make, auth, sharing=True)
    stranger = make.user()
    admin_id, admin_header = admin_auth
    before = make.link_row(link_id)

    for path, method, body in (
        (_sharing(link_id), "PATCH", {"sharing_enabled": False}),
        (_sharing(link_id), "PATCH", {"sharing_enabled": True}),
        (_revoke(link_id), "POST", None),
        (CAREGIVERS, "GET", None),
    ):
        assert client.request(method, path, json=body).status_code == 401

    for actor, headers in (
        (family, auth(family)),
        (stranger, auth(stranger)),
        (admin_id, admin_header),
    ):
        for enabled in (False, True):
            r = client.patch(_sharing(link_id), json={"sharing_enabled": enabled}, headers=headers)
            assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
        r = client.post(_revoke(link_id), headers=headers)
        assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
        assert make.link_row(link_id) == before

        denied = make.family_audit_events(actor_id=actor)
        assert [(a["operation"], a["result"], a["reason"]) for a in denied] == [
            ("disable_sharing", "denied", "khong_co_quyen"),
            ("enable_sharing", "denied", "khong_co_quyen"),
            ("revoke", "denied", "khong_co_quyen"),
        ]
        expected_scope = (None, None) if actor == admin_id else (patient, link_id)
        assert all((a["patient_user_id"], a["link_id"]) == expected_scope for a in denied)

    admin_list = client.get(CAREGIVERS, headers=admin_header)
    assert admin_list.status_code == 403 and admin_list.json() == {"detail": "khong_co_quyen"}
    assert [a["operation"] for a in make.family_audit_events(actor_id=admin_id)][-1] == (
        "list_caregivers"
    )
    # Người thân và người lạ gọi danh sách: chỉ thấy liên kết mà chính họ là patient (không có).
    for other in (family, stranger):
        r = client.get(CAREGIVERS, headers=auth(other))
        assert r.status_code == 200 and r.json() == {"items": []}

    # Cặp allowed: đúng patient hủy được.
    assert client.post(_revoke(link_id), headers=auth(patient)).status_code == 200
