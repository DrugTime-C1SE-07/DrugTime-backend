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
