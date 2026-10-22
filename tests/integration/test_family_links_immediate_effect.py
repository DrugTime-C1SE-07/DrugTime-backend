"""Quyết định của patient có hiệu lực ngay ở request kế tiếp (adhoc-20261020-family-link-approval).

Kịch bản chất lượng "rút quyền rồi gửi request ngay → 403": người thân dùng MỘT token suốt chuỗi,
mọi thay đổi của patient đi qua endpoint thật. Mỗi bước kiểm cả response đọc dữ liệu sức khỏe
(`GET /medications/{id}`, qua PEP), dòng `access_logs` mới nhất, và danh sách người nhận cảnh báo
(`access.authorized_caregivers`, đọc DB mỗi lần gọi). Bao phủ AC6.
"""

from uuid import uuid4

from tests.integration.test_family_links_access import _create_user_medication

from drugtime.modules.access import api as access
from drugtime.shared.db import unit_of_work

VERSION = "2026-10-v1"


def _recipients(patient):
    with unit_of_work() as uow:
        return access.authorized_caregivers(uow, patient)


def test_every_decision_applies_on_next_request_same_token__AC6(client, db, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)  # một token duy nhất cho cả chuỗi
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())
    code = client.get("/family/link-code", headers=patient_headers).json()["code"]

    def send_request():
        r = client.post(
            "/family/link-requests",
            json={"client_uuid": str(uuid4()), "code": code},
            headers=family_headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def family_reads(expected_status, expected_log):
        r = client.get(f"/medications/{user_med_id}", headers=family_headers)
        assert r.status_code == expected_status, r.text
        last = make.access_logs(patient)[-1]
        assert (last["actor_user_id"], last["result"]) == (family, expected_log)
        # PEP ghi vai trò theo quyền tại thời điểm đó: chỉ dòng allowed mang vai trò family.
        if expected_log == "allowed":
            assert last["actor_role"] == "family"
        assert (family in _recipients(patient)) is (expected_log == "allowed")

    def set_sharing(link_id, enabled):
        r = client.patch(
            f"/family/links/{link_id}/sharing",
            json={"sharing_enabled": enabled},
            headers=patient_headers,
        )
        assert r.status_code == 200, r.text

    # (a) Yêu cầu đang chờ: chưa có quyền.
    link_id = send_request()
    family_reads(403, "denied")

    # (b) Chấp thuận: liên kết active nhưng chia sẻ đang tắt → vẫn 403.
    r = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": VERSION,
        },
        headers=patient_headers,
    )
    assert r.status_code == 200 and r.json()["sharing_enabled"] is False
    family_reads(403, "denied")

    # (c) Bật chia sẻ → request kế tiếp đọc được, có trong danh sách nhận cảnh báo.
    set_sharing(link_id, True)
    family_reads(200, "allowed")

    # (d) Tắt chia sẻ → request kế tiếp bị từ chối.
    set_sharing(link_id, False)
    family_reads(403, "denied")

    # (e) Bật lại rồi hủy liên kết → request kế tiếp bị từ chối dù token vẫn còn hạn.
    set_sharing(link_id, True)
    family_reads(200, "allowed")
    assert (
        client.post(f"/family/links/{link_id}/revoke", headers=patient_headers).status_code == 200
    )
    family_reads(403, "denied")

    # (f) Gửi lại yêu cầu và bị từ chối → vẫn 403.
    new_link = send_request()
    assert new_link != link_id
    r = client.post(f"/family/links/{new_link}/reject", headers=patient_headers)
    assert r.status_code == 200
    family_reads(403, "denied")


def test_consent_withdrawal_blocks_even_with_sharing_on__AC6(client, db, make, auth):
    """Công tắc bật nhưng patient rút family_sharing: request kế tiếp bị từ chối (QD-28)."""
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())
    link_id = make.pending_link(patient, family)
    client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": VERSION,
        },
        headers=auth(patient),
    )
    client.patch(
        f"/family/links/{link_id}/sharing", json={"sharing_enabled": True}, headers=auth(patient)
    )
    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 200

    make.revoke_consent(patient, "family_sharing")

    r = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r.status_code == 403
    assert make.access_logs(patient)[-1]["result"] == "denied"
    assert family not in _recipients(patient)
    assert make.link_row(link_id)["sharing_enabled"] is True  # công tắc không tự đổi
