from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text

from drugtime.modules.identity.application.sign_in import issue_app_session
from drugtime.modules.identity.domain.user import SessionType

PATH = "/family/patients"


def logs(db, caller):
    return (
        db.execute(
            text(
                "SELECT patient_user_id, actor_role::text, data_scope::text, result::text "
                "FROM access_logs WHERE actor_user_id=:a ORDER BY id"
            ),
            {"a": caller},
        )
        .mappings()
        .all()
    )


def linked(make, caller, *, name="An", consents=("health_data", "family_sharing"), **kw):
    patient = make.user(consents=consents)
    make.db.execute(text("UPDATE users SET full_name=:n WHERE id=:p"), {"n": name, "p": patient})
    lid = make.link(patient, caller, **kw)
    return patient, lid


def test_returns_multiple_patients_with_minimal_fields_and_allowed_logs__AC1_AC8_AC10(
    client, make, auth, db
):
    caller = make.user(consents=())
    first, _ = linked(make, caller, name=" An ")
    second, _ = linked(make, caller, name="An")
    missing, _ = linked(make, caller, name=None)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    items = response.json()["items"]
    expected = sorted((first, second)) + [missing]
    assert [UUID(i["patient_id"]) for i in items] == expected
    assert [i["patient_full_name"] for i in items] == ["An", "An", None]
    assert all(set(i) == {"patient_id", "patient_full_name"} for i in items)
    records = logs(db, caller)
    assert len(records) == 3
    assert {r["patient_user_id"] for r in records} == set(expected)
    assert all(
        (r["actor_role"], r["data_scope"], r["result"])
        == ("family", "danh_sach_benh_nhan_lien_ket", "allowed")
        for r in records
    )
    assert make.family_audit_events(actor_id=caller) == []


@pytest.mark.parametrize(
    "condition",
    ["pending", "rejected", "revoked", "unshared", "legacy", "no_health", "no_family", "unrelated"],
)
def test_filters_unrelated_inactive_unshared_and_missing_consents__AC2_AC7_AC9(
    client, make, auth, db, condition
):
    caller = make.user()
    good, _ = linked(make, caller)
    options = {}
    consents = ("health_data", "family_sharing")
    target = caller
    if condition in ("pending", "rejected", "revoked"):
        options = {"status": condition}
    elif condition == "unshared":
        options = {"sharing": False}
    elif condition == "legacy":
        options = {"legacy": True}
    elif condition == "no_health":
        consents = ("family_sharing",)
    elif condition == "no_family":
        consents = ("health_data",)
    else:
        target = make.user()
    other, _ = linked(make, target, consents=consents, **options)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 200, response.text
    assert [i["patient_id"] for i in response.json()["items"]] == [str(good)]
    assert other != good
    assert [r["patient_user_id"] for r in logs(db, caller)] == [good]


@pytest.mark.parametrize("change", ["sharing", "health_data", "family_sharing", "revoke"])
def test_revocation_applies_next_request_with_same_token__AC3_AC7_AC9(
    client, make, auth, db, change
):
    caller = make.user()
    patient, lid = linked(make, caller)
    headers = auth(caller)
    assert len(client.get(PATH, headers=headers).json()["items"]) == 1
    if change in ("health_data", "family_sharing"):
        make.revoke_consent(patient, change)
    elif change == "sharing":
        r = client.patch(
            f"/family/links/{lid}/sharing", headers=auth(patient), json={"sharing_enabled": False}
        )
        assert r.status_code == 200, r.text
    else:
        r = client.post(f"/family/links/{lid}/revoke", headers=auth(patient))
        assert r.status_code in (200, 204), r.text
    response = client.get(PATH, headers=headers)
    assert response.status_code == 200 and response.json() == {"items": []}
    assert len(logs(db, caller)) == 1  # only the first authorized read
    event = make.family_audit_events(actor_id=caller)[-1]
    assert (event["operation"], event["result"], event["patient_user_id"], event["link_id"]) == (
        "list_linked_patients",
        "allowed",
        None,
        None,
    )
    if change in ("health_data", "family_sharing"):
        make.consent(patient, change)
    elif change == "sharing":
        r = client.patch(
            f"/family/links/{lid}/sharing", headers=auth(patient), json={"sharing_enabled": True}
        )
        assert r.status_code == 200
    else:
        make.link(patient, caller, sharing=False)
        assert client.get(PATH, headers=headers).json() == {"items": []}
        return
    assert len(client.get(PATH, headers=headers).json()["items"]) == 1


@pytest.mark.parametrize("admin", [False, True])
def test_empty_list_and_admin_denial_durable_request_audit__AC2_AC4_AC6_AC11(
    client, make, auth, db, admin
):
    caller = make.user(admin=admin, consents=())
    if admin:
        linked(make, caller)
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == (403 if admin else 200), response.text
    assert response.json() == ({"detail": "khong_co_quyen"} if admin else {"items": []})
    assert logs(db, caller) == []
    events = make.family_audit_events(actor_id=caller)
    assert len(events) == 1
    assert (events[0]["result"], events[0]["patient_user_id"], events[0]["link_id"]) == (
        "denied" if admin else "allowed",
        None,
        None,
    )
    assert events[0]["reason"] == ("khong_co_quyen" if admin else None)


@pytest.mark.parametrize(
    "query,body",
    [
        ("patient_id=x", None),
        ("user_id=x", None),
        ("limit=1", None),
        ("cursor=x", None),
        ("x=1&x=2", None),
        ("", b"{}"),
        ("", b"null"),
    ],
)
def test_rejects_selectors_and_body_and_returns_no_store__AC4_AC8(client, make, auth, query, body):
    response = client.request(
        "GET", PATH + ("?" + query if query else ""), headers=auth(make.user()), content=body
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.headers["cache-control"] == "no-store"


def test_missing_invalid_and_deleted_token__AC4(client, make, auth, db):
    caller = make.user()
    expired = issue_app_session(caller, SessionType.MOBILE, datetime(2000, 1, 1, tzinfo=UTC)).token
    for headers in (
        {},
        {"Authorization": "Bearer invalid"},
        {"Authorization": "Bearer " + expired},
    ):
        response = client.get(PATH, headers=headers)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
    headers = auth(caller)
    db.execute(
        text("UPDATE users SET erased_at=now(),email=NULL,full_name=NULL WHERE id=:u"),
        {"u": caller},
    )
    assert client.get(PATH, headers=headers).status_code == 401


def test_unicode_blank_name_order_is_stable__AC1_AC8(client, make, auth):
    caller = make.user()
    patients = [linked(make, caller, name=name)[0] for name in ("Án", "an", " An ", " ", "💊")]
    response = client.get(PATH, headers=auth(caller))
    assert response.status_code == 200, response.text
    assert [i["patient_full_name"] for i in response.json()["items"]] == [
        "An",
        "an",
        "Án",
        "💊",
        None,
    ]
    assert {i["patient_id"] for i in response.json()["items"]} == {str(p) for p in patients}
