"""Kiểm tra tương tranh quyết định duyệt/từ chối liên kết gia đình và rút consent (task 3.16).

Bao phủ kịch bản I7 và I12 theo AC5, AC9, AC15, AC17.
"""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text

from drugtime.main import create_app


def _create_pending_link(db, patient_id: UUID, family_id: UUID) -> int:
    return db.execute(
        text(
            "INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled) "
            "VALUES (:p, :f, 'pending', false) RETURNING id"
        ),
        {"p": patient_id, "f": family_id},
    ).scalar_one()


# ==============================================================================
# I7: Concurrent decisions (AC5, 9, 15, 17)
# ==============================================================================


def test_concurrent_approve_same_payload_both_200_single_evidence__AC5_AC9(
    db, make, auth
):
    """AC5, AC9: Hai request approve đồng thời với cùng payload:

    cả hai đều nhận 200, nhưng DB chỉ commit đúng 1 bản ghi evidence.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    app = create_app()

    def call_approve():
        c = TestClient(app)
        return c.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_approve), executor.submit(call_approve)]
        responses = [f.result() for f in futures]

    assert all(r.status_code == 200 for r in responses)

    # Khẳng định chỉ có duy nhất 1 bản ghi bằng chứng được lưu
    confirmations = make.consent_confirmations(link_id)
    assert len(confirmations) == 1
    assert confirmations[0]["document_version"] == "2026-10-v1"

    # Trạng thái link là active
    status = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).scalar_one()
    assert status == "active"


def test_concurrent_approve_different_versions_one_wins_other_conflict__AC9(
    db, make, auth
):
    """AC9: Hai request approve đồng thời nhưng khác document_version:

    bên thắng nhận 200, bên thua nhận 409 conflict, không ghi đè version.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    app = create_app()

    def call_approve(version: str):
        c = TestClient(app)
        body = {
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": version,
        }
        return c.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(call_approve, "2026-10-v1")
        f2 = executor.submit(call_approve, "2026-11-v2")
        r1, r2 = f1.result(), f2.result()

    # Request với version hiện hành 2026-10-v1 phải thành công 200
    assert r1.status_code == 200

    # Request với version khác bị từ chối (422 invalid_document_version hoặc 409 nếu chạy sau)
    assert r2.status_code in (409, 422)

    # Chỉ có 1 bản ghi evidence với version hiện hành
    confirmations = make.consent_confirmations(link_id)
    assert len(confirmations) == 1
    assert confirmations[0]["document_version"] == "2026-10-v1"


def test_concurrent_reject_both_200_same_timestamp__AC15(db, make, auth):
    """AC15: Hai request reject đồng thời cho cùng một pending link:

    cả hai đều nhận 200 và trả về cùng một rejected_at timestamp (idempotent).
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    app = create_app()

    def call_reject():
        c = TestClient(app)
        return c.post(f"/family/links/{link_id}/reject", headers=auth(patient))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_reject), executor.submit(call_reject)]
        responses = [f.result() for f in futures]

    assert all(r.status_code == 200 for r in responses)
    t1 = responses[0].json()["rejected_at"]
    t2 = responses[1].json()["rejected_at"]
    assert t1 == t2

    status = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).scalar_one()
    assert status == "rejected"


def test_concurrent_approve_and_reject_one_wins_other_409__AC17(db, make, auth):
    """AC17: Một request approve và một request reject chạy đồng thời:

    chỉ một bên commit thành công (200), bên còn lại nhận 409 conflict.
    Không bao giờ có trạng thái mâu thuẫn (vừa rejected vừa có evidence).
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    app = create_app()

    def call_approve():
        c = TestClient(app)
        return c.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))

    def call_reject():
        c = TestClient(app)
        return c.post(f"/family/links/{link_id}/reject", headers=auth(patient))

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_app = executor.submit(call_approve)
        f_rej = executor.submit(call_reject)
        r_app, r_rej = f_app.result(), f_rej.result()

    statuses = {r_app.status_code, r_rej.status_code}
    assert statuses == {200, 409}

    final_status = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).scalar_one()

    confirmations = make.consent_confirmations(link_id)

    if r_app.status_code == 200:
        # Approve thắng: link active, có đúng 1 confirmation
        assert r_rej.status_code == 409
        assert final_status == "active"
        assert len(confirmations) == 1
    else:
        # Reject thắng: link rejected, KHÔNG có confirmation
        assert r_rej.status_code == 200
        assert final_status == "rejected"
        assert len(confirmations) == 0


# ==============================================================================
# I12: Concurrent withdrawal and approve order (AC6, 7, 10, 11)
# ==============================================================================


def test_consent_revocation_committed_before_approve_causes_403__AC7_AC10(
    db, make, auth
):
    """AC7, AC10: Nếu consent family_sharing bị thu hồi trước khi approve hoàn tất,

    thì approve bị từ chối 403 consent_missing, không chuyển link sang active.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    # Rút consent trước
    make.revoke_consent(patient, "family_sharing")

    app = create_app()
    c = TestClient(app)
    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r = c.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r.status_code == 403
    assert r.json()["detail"] in ("consent_revoked", "consent_missing")

    # Link vẫn pending, không có evidence
    status = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).scalar_one()
    assert status == "pending"
    assert len(make.consent_confirmations(link_id)) == 0
