from collections.abc import Iterator
from datetime import UTC, datetime
from socket import create_connection
from time import perf_counter
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work


def _require_db() -> None:
    parsed = urlparse(get_settings().database_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    try:
        with create_connection((host, port), timeout=1):
            pass
    except OSError as exc:
        pytest.skip(f"local integration database is not available: {exc}")


@pytest.fixture(autouse=True)
def require_db() -> None:
    _require_db()


@pytest.fixture
def client_as() -> Iterator:
    app = create_app()

    def factory(user_id: UUID) -> TestClient:
        app.dependency_overrides[identity.current_user] = lambda: CurrentUser(
            id=user_id,
            is_admin=False,
        )
        return TestClient(app)

    yield factory
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(create_app())


def _seed_patient_schedule(patient_id: UUID | None = None) -> tuple[UUID, int]:
    patient_id = patient_id or uuid4()
    suffix = uuid4().hex
    with unit_of_work() as uow:
        uow.connection.execute(
            text("""
            INSERT INTO users (id, email)
            VALUES (:id, :email)
            ON CONFLICT (id) DO NOTHING
            """),
            {"id": patient_id, "email": f"patient-{suffix}@example.test"},
        )
        uow.connection.execute(
            text("""
            INSERT INTO user_consents (user_id, consent_type, status, document_version)
            SELECT :user_id, 'health_data', 'dong_y', 'test-v1'
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_consents
                WHERE user_id = :user_id
                  AND consent_type = 'health_data'
                  AND document_version = 'test-v1'
            )
            """),
            {"user_id": patient_id},
        )
        medication_id = uow.connection.execute(
            text("INSERT INTO medications (name) VALUES (:name) RETURNING id"),
            {"name": f"Medication {suffix}"},
        ).scalar_one()
        prescription_id = uow.connection.execute(
            text("""
            INSERT INTO prescriptions (user_id, entry_source)
            VALUES (:user_id, 'thu_cong')
            RETURNING id
            """),
            {"user_id": patient_id},
        ).scalar_one()
        user_medication_id = uow.connection.execute(
            text("""
            INSERT INTO user_medications (
                user_id, prescription_id, medication_id, entry_method,
                quantity_per_dose, doses_per_day
            )
            VALUES (:user_id, :prescription_id, :medication_id, 'thu_cong', 1, 1)
            RETURNING id
            """),
            {
                "user_id": patient_id,
                "prescription_id": prescription_id,
                "medication_id": medication_id,
            },
        ).scalar_one()
        schedule_id = uow.connection.execute(
            text("""
            INSERT INTO medication_schedules (
                user_medication_id, intake_time, days_of_week, effective_from
            )
            VALUES (:user_medication_id, '08:00', ARRAY[1]::smallint[], :effective_from)
            RETURNING id
            """),
            {
                "user_medication_id": user_medication_id,
                "effective_from": datetime(2026, 10, 1, tzinfo=UTC),
            },
        ).scalar_one()
    return patient_id, schedule_id


def _seed_user() -> UUID:
    user_id = uuid4()
    with unit_of_work() as uow:
        uow.connection.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": user_id, "email": f"user-{uuid4().hex}@example.test"},
        )
    return user_id


def _post_item(client: TestClient, item: dict) -> dict:
    response = client.post("/doses/batch", json=[item])
    assert response.status_code == 200
    return response.json()


def _dose_count(schedule_id: int, scheduled_at: datetime) -> int:
    with unit_of_work() as uow:
        return uow.connection.execute(
            text("""
            SELECT count(*)
            FROM dose_logs
            WHERE medication_schedule_id = :schedule_id AND scheduled_at = :scheduled_at
            """),
            {"schedule_id": schedule_id, "scheduled_at": scheduled_at},
        ).scalar_one()


def test_post_doses_batch_creates_dose_log_for_authenticated_patient__AC1_AC10_AC18(
    client_as,
):
    patient_id, schedule_id = _seed_patient_schedule()
    client_uuid = str(uuid4())

    payload = {
        "client_uuid": client_uuid,
        "schedule_id": schedule_id,
        "scheduled_at": "2026-10-02T01:00:59.999Z",
        "taken_at": "2026-10-02T01:05:59.999Z",
    }
    body = _post_item(client_as(patient_id), payload)

    assert body["summary"] == {"total": 1, "synced": 1, "failed": 0}
    item = body["items"][0]
    assert item["result"] == "synced"
    assert item["dose_status"] == "da_uong"
    assert item["scheduled_at"] == "2026-10-02T01:00:00Z"

    with unit_of_work() as uow:
        row = uow.connection.execute(
            text("""
            SELECT scheduled_at, taken_at, status, client_uuid, synced_at
            FROM dose_logs
            WHERE id = :id
            """),
            {"id": item["dose_log_id"]},
        ).one()
    assert row.scheduled_at == datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    assert row.taken_at == datetime(2026, 10, 2, 1, 5, tzinfo=UTC)
    assert row.status == "da_uong"
    assert str(row.client_uuid) == client_uuid
    assert row.synced_at is not None


def test_post_doses_batch_is_idempotent_for_same_client_uuid__AC2(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    payload = {
        "client_uuid": str(uuid4()),
        "schedule_id": schedule_id,
        "scheduled_at": "2026-10-02T01:00:00Z",
        "taken_at": "2026-10-02T01:05:00Z",
    }
    client = client_as(patient_id)

    first = _post_item(client, payload)
    second = _post_item(client, payload)

    assert first["items"][0]["dose_log_id"] == second["items"][0]["dose_log_id"]
    assert _dose_count(schedule_id, datetime(2026, 10, 2, 1, 0, tzinfo=UTC)) == 1


def test_post_doses_batch_partial_success_and_client_uuid_conflict__AC2_AC7(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    client_uuid = str(uuid4())
    client = client_as(patient_id)
    synced_payload = {
        "client_uuid": client_uuid,
        "schedule_id": schedule_id,
        "scheduled_at": "2026-10-02T01:00:00Z",
        "taken_at": "2026-10-02T01:05:00Z",
    }
    _post_item(client, synced_payload)
    _, another_schedule_id = _seed_patient_schedule(patient_id)

    response = client.post(
        "/doses/batch",
        json=[
            {
                "client_uuid": str(uuid4()),
                "schedule_id": another_schedule_id,
                "scheduled_at": "2026-10-02T02:00:00Z",
                "taken_at": "2026-10-02T02:05:00Z",
            },
            {
                **synced_payload,
                "taken_at": "2026-10-02T01:06:00Z",
            },
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"total": 2, "synced": 1, "failed": 1}
    assert body["items"][0]["result"] == "synced"
    assert body["items"][1]["error"]["code"] == "client_uuid_conflict"
    assert body["items"][1]["error"]["http_status"] == 409


def test_post_doses_batch_updates_missed_row_to_late__AC3(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    with unit_of_work() as uow:
        uow.connection.execute(
            text("""
            INSERT INTO dose_logs (medication_schedule_id, scheduled_at, status)
            VALUES (:schedule_id, :scheduled_at, 'bo_lo')
            """),
            {"schedule_id": schedule_id, "scheduled_at": scheduled_at},
        )

    body = _post_item(
        client_as(patient_id),
        {
            "client_uuid": str(uuid4()),
            "schedule_id": schedule_id,
            "scheduled_at": "2026-10-02T01:00:00Z",
            "taken_at": "2026-10-02T01:31:00Z",
        },
    )

    assert body["items"][0]["dose_status"] == "uong_tre"
    assert _dose_count(schedule_id, scheduled_at) == 1


def test_post_doses_batch_does_not_overwrite_confirmed_row__AC4(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    original_taken_at = datetime(2026, 10, 2, 1, 5, tzinfo=UTC)
    with unit_of_work() as uow:
        uow.connection.execute(
            text("""
            INSERT INTO dose_logs (
                medication_schedule_id, scheduled_at, taken_at, status, client_uuid, synced_at
            )
            VALUES (:schedule_id, :scheduled_at, :taken_at, 'da_uong', :client_uuid, now())
            """),
            {
                "schedule_id": schedule_id,
                "scheduled_at": scheduled_at,
                "taken_at": original_taken_at,
                "client_uuid": uuid4(),
            },
        )

    body = _post_item(
        client_as(patient_id),
        {
            "client_uuid": str(uuid4()),
            "schedule_id": schedule_id,
            "scheduled_at": "2026-10-02T01:00:00Z",
            "taken_at": "2026-10-02T01:20:00Z",
        },
    )

    assert body["items"][0]["dose_status"] == "da_uong"
    with unit_of_work() as uow:
        taken_at = uow.connection.execute(
            text("""
            SELECT taken_at FROM dose_logs
            WHERE medication_schedule_id = :schedule_id AND scheduled_at = :scheduled_at
            """),
            {"schedule_id": schedule_id, "scheduled_at": scheduled_at},
        ).scalar_one()
    assert taken_at == original_taken_at


def test_post_doses_batch_rejects_invalid_time_windows_per_item__AC5_AC15(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    _, another_schedule_id = _seed_patient_schedule(patient_id)

    response = client_as(patient_id).post(
        "/doses/batch",
        json=[
            {
                "client_uuid": str(uuid4()),
                "schedule_id": schedule_id,
                "scheduled_at": "2026-10-02T01:00:00Z",
                "taken_at": "2099-10-02T01:00:00Z",
            },
            {
                "client_uuid": str(uuid4()),
                "schedule_id": another_schedule_id,
                "scheduled_at": "2026-10-02T16:50:00Z",
                "taken_at": "2026-10-02T16:19:59.999999Z",
            },
        ],
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["error"]["code"] == "taken_at_in_future"
    assert items[1]["error"]["code"] == "taken_at_too_early"


def test_post_doses_batch_forbidden_cross_patient_schedule_logs_denied__AC8(client_as):
    actor_id = _seed_user()
    patient_id, schedule_id = _seed_patient_schedule()

    body = _post_item(
        client_as(actor_id),
        {
            "client_uuid": str(uuid4()),
            "schedule_id": schedule_id,
            "scheduled_at": "2026-10-02T01:00:00Z",
            "taken_at": "2026-10-02T01:05:00Z",
        },
    )

    assert body["items"][0]["result"] == "failed"
    assert body["items"][0]["error"]["code"] == "forbidden_schedule"
    assert body["items"][0]["error"]["http_status"] == 403
    assert _dose_count(schedule_id, datetime(2026, 10, 2, 1, 0, tzinfo=UTC)) == 0
    with unit_of_work() as uow:
        denied = uow.connection.execute(
            text("""
            SELECT count(*)
            FROM access_logs
            WHERE actor_user_id = :actor_id
              AND patient_user_id = :patient_id
              AND data_scope = 'lich_su_tuan_thu'
              AND result = 'denied'
            """),
            {"actor_id": actor_id, "patient_id": patient_id},
        ).scalar_one()
    assert denied >= 1


@pytest.mark.xfail(
    reason=(
        "AC9 depends on the shared identity.current_user dependency; "
        "the user decided not to modify module identity in task 2.10."
    ),
)
def test_post_doses_batch_requires_authentication__AC9(anonymous_client):
    _, schedule_id = _seed_patient_schedule()

    response = anonymous_client.post(
        "/doses/batch",
        json=[
            {
                "client_uuid": str(uuid4()),
                "schedule_id": schedule_id,
                "scheduled_at": "2026-10-02T01:00:00Z",
                "taken_at": "2026-10-02T01:05:00Z",
            }
        ],
    )

    assert response.status_code == 401


def test_post_doses_batch_missing_schedule_item_404__AC16(client_as):
    patient_id, _ = _seed_patient_schedule()

    body = _post_item(
        client_as(patient_id),
        {
            "client_uuid": str(uuid4()),
            "schedule_id": 9_999_999_999,
            "scheduled_at": "2026-10-02T01:00:00Z",
            "taken_at": "2026-10-02T01:05:00Z",
        },
    )

    assert body["items"][0]["error"]["code"] == "schedule_not_found"
    assert body["items"][0]["error"]["http_status"] == 404


def test_post_doses_batch_p95_under_two_seconds_for_small_batches__AC17(client_as):
    patient_id, schedule_id = _seed_patient_schedule()
    client = client_as(patient_id)
    elapsed = []

    for i in range(10):
        started = perf_counter()
        response = client.post(
            "/doses/batch",
            json=[
                {
                    "client_uuid": str(uuid4()),
                    "schedule_id": schedule_id,
                    "scheduled_at": f"2026-10-02T{i:02d}:00:00Z",
                    "taken_at": f"2026-10-02T{i:02d}:05:00Z",
                }
            ],
        )
        elapsed.append(perf_counter() - started)
        assert response.status_code == 200
        assert response.json()["summary"]["failed"] == 0

    elapsed.sort()
    p95 = elapsed[int(len(elapsed) * 0.95) - 1]
    assert p95 < 2
