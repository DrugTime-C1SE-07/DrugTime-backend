import pytest


@pytest.mark.parametrize(
    "mode", ["self", "linked", "unlinked", "sharing_off", "no_health", "admin"]
)
def test_patient_medications_permissions_and_audit__AC13(client, make, auth, mode):
    patient = make.user(
        consents=("health_data", "family_sharing") if mode != "no_health" else ("family_sharing",)
    )
    caller = patient if mode == "self" else make.user(admin=mode == "admin")
    if mode in ("linked", "sharing_off", "no_health"):
        make.link(patient, caller, sharing=mode != "sharing_off")
    response = client.get(f"/patients/{patient}/medications", headers=auth(caller))
    allowed = mode in ("self", "linked")
    assert response.status_code == (200 if allowed else 403)
    assert response.headers["cache-control"] == "no-store"
    logs = make.access_logs(patient)
    assert any(
        log["actor_user_id"] == caller and log["result"] == ("allowed" if allowed else "denied")
        for log in logs
    )


def test_revoke_sharing_affects_next_request__AC14(client, make, auth, db):
    from sqlalchemy import text

    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link = make.link(patient, family, sharing=True)
    headers = auth(family)
    assert client.get(f"/patients/{patient}/medications", headers=headers).status_code == 200
    db.execute(
        text("UPDATE caregiver_links SET sharing_enabled = false WHERE id = :id"), {"id": link}
    )
    assert client.get(f"/patients/{patient}/medications", headers=headers).status_code == 403
    assert any(
        log["result"] == "denied" and log["actor_user_id"] == family
        for log in make.access_logs(patient)
    )


def test_other_patient_id_is_denied_and_audited__AC20(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    other_patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    make.link(patient, family)
    headers = auth(family)
    assert client.get(f"/patients/{patient}/medications", headers=headers).status_code == 200
    denied = client.get(f"/patients/{other_patient}/medications", headers=headers)
    assert denied.status_code == 403
    assert any(
        log["actor_user_id"] == family and log["result"] == "denied"
        for log in make.access_logs(other_patient)
    )


def test_withdrawn_consent_blocks_next_request__AC14(client, make, auth):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    make.link(patient, family)
    headers = auth(family)
    path = f"/patients/{patient}/medications"
    assert client.get(path, headers=headers).status_code == 200
    make.revoke_consent(patient, "health_data")
    assert client.get(path, headers=headers).status_code == 403
    assert any(
        log["actor_user_id"] == family and log["result"] == "denied"
        for log in make.access_logs(patient)
    )

def _patient_with_pill(client, make, auth, scheduled_body):
    patient = make.user(consents=("health_data", "family_sharing"))
    body = scheduled_body(make.catalog_medication(), pill_shape="softgel", pill_color="green")
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 201, r.text
    return patient, r.json()["id"]


def test_linked_family_sees_pill_appearance_and_is_audited__AC20(
    client, make, auth, scheduled_body
):
    patient, med_id = _patient_with_pill(client, make, auth, scheduled_body)
    family = make.user()
    make.link(patient, family)
    r = client.get(f"/patients/{patient}/medications", headers=auth(family))
    assert r.status_code == 200
    item = next(m for m in r.json()["items"] if m["id"] == med_id)
    assert (item["pill_shape"], item["pill_color"]) == ("softgel", "green")
    assert any(
        log["actor_user_id"] == family and log["result"] == "allowed"
        for log in make.access_logs(patient)
    )


@pytest.mark.parametrize("case", ["unlinked", "sharing_off", "no_family_sharing"])
def test_denied_family_gets_403_without_appearance_and_denied_log__AC20(
    client, make, auth, scheduled_body, case
):
    patient, _ = _patient_with_pill(client, make, auth, scheduled_body)
    family = make.user()
    if case == "sharing_off":
        make.link(patient, family, sharing=False)
    elif case == "no_family_sharing":
        make.link(patient, family)
        make.revoke_consent(patient, "family_sharing")
    r = client.get(f"/patients/{patient}/medications", headers=auth(family))
    assert r.status_code == 403
    assert "pill_" not in r.text
    assert any(
        log["actor_user_id"] == family and log["result"] == "denied"
        for log in make.access_logs(patient)
    )


def test_unlink_then_immediate_request_403__AC20(client, make, auth, db, scheduled_body):
    from sqlalchemy import text

    patient, _ = _patient_with_pill(client, make, auth, scheduled_body)
    family = make.user()
    link = make.link(patient, family)
    headers = auth(family)
    assert client.get(f"/patients/{patient}/medications", headers=headers).status_code == 200
    db.execute(
        text("UPDATE caregiver_links SET status = 'revoked', revoked_at = now() WHERE id = :id"),
        {"id": link},
    )
    assert client.get(f"/patients/{patient}/medications", headers=headers).status_code == 403
