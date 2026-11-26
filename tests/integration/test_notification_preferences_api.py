"""Tùy chọn "Báo người giám sát khi bỏ lỡ liều" và tác động lên người nhận cảnh báo."""

from drugtime.modules.adherence.adapters.outbound.other_modules import AccessGuardAdapter
from drugtime.shared.db import unit_of_work

PATH = "/me/notification-preferences"


def recipients(patient_id):
    with unit_of_work() as uow:
        return AccessGuardAdapter().caregivers_of(uow, patient_id)


def test_default_on_and_round_trip(client, make, auth):
    h = auth(make.user())
    assert client.get(PATH, headers=h).json() == {"missed_dose_family_alerts": True}
    response = client.put(PATH, headers=h, json={"missed_dose_family_alerts": False})
    assert response.status_code == 200
    assert response.json() == {"missed_dose_family_alerts": False}
    assert client.get(PATH, headers=h).json() == {"missed_dose_family_alerts": False}


def test_rejects_admin_anonymous_and_bad_body(client, make, auth):
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers=auth(make.user(admin=True))).status_code == 403
    h = auth(make.user())
    assert client.put(PATH, headers=h, json={}).status_code == 422
    body = {"missed_dose_family_alerts": True, "patient_id": "x"}
    assert client.put(PATH, headers=h, json=body).status_code == 422


def test_turning_off_removes_missed_dose_recipients_on_next_read(client, make, auth):
    patient = make.user()
    family = make.family_of(patient)
    h = auth(patient)
    assert recipients(patient) == [family]
    client.put(PATH, headers=h, json={"missed_dose_family_alerts": False})
    assert recipients(patient) == []
    client.put(PATH, headers=h, json={"missed_dose_family_alerts": True})
    assert recipients(patient) == [family]
