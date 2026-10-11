"""Integration coverage for the Admin catalog sync history endpoint."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

SOURCE = "duoc_thu_qg"


def _insert_run(db, *, status, started_at, details=None):
    finished_at = None if status == "dang_chay" else started_at + timedelta(seconds=5)
    return db.execute(
        text(
            "INSERT INTO catalog_sync_runs "
            "(source, started_at, finished_at, status, records_inserted, records_updated, "
            "records_failed, error_details, triggered_by) VALUES "
            "(CAST(:source AS catalog_source), :started_at, :finished_at, "
            "CAST(:status AS sync_status), 2, 1, 1, CAST(:details AS jsonb), 'scheduler') "
            "RETURNING id"
        ),
        {
            "source": SOURCE,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "details": details,
        },
    ).scalar_one()


def test_admin_lists_filtered_paginated_history__AC7(client, db, make, auth):
    admin = make.user(admin=True)
    db.execute(
        text("DELETE FROM catalog_sync_runs WHERE source=CAST(:source AS catalog_source)"),
        {"source": SOURCE},
    )
    base = datetime(2040, 1, 1, tzinfo=UTC)
    older = _insert_run(db, status="thanh_cong", started_at=base, details=None)
    newer = _insert_run(
        db,
        status="thanh_cong",
        started_at=base + timedelta(seconds=1),
        details='{"code":"invalid_record","groups":[{"code":"invalid_record","count":1}]}',
    )

    response = client.get(
        "/admin/catalog/sync-runs",
        params={"source": SOURCE, "status": "thanh_cong", "limit": 1, "offset": 0},
        headers=auth(admin),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == newer
    assert body["total"] >= 2
    assert (body["limit"], body["offset"]) == (1, 0)
    assert body["items"][0]["error_details"]["code"] == "invalid_record"

    second_page = client.get(
        "/admin/catalog/sync-runs",
        params={"source": SOURCE, "status": "thanh_cong", "limit": 1, "offset": 1},
        headers=auth(admin),
    ).json()
    assert second_page["items"][0]["id"] == older


def test_history_requires_admin_and_valid_query__AC8(client, db, make, auth):
    user = make.user()

    assert client.get("/admin/catalog/sync-runs").status_code == 401
    assert client.get("/admin/catalog/sync-runs", headers=auth(user)).status_code == 403

    admin = make.user(admin=True)
    assert (
        client.get(
            "/admin/catalog/sync-runs", params={"limit": 0}, headers=auth(admin)
        ).status_code
        == 422
    )


def test_admin_role_revocation_applies_on_next_request__AC8(client, db, make, auth):
    admin = make.user(admin=True)
    headers = auth(admin)
    assert client.get("/admin/catalog/sync-runs", headers=headers).status_code == 200

    db.execute(text("UPDATE users SET system_role='user' WHERE id=:id"), {"id": admin})

    assert client.get("/admin/catalog/sync-runs", headers=headers).status_code == 403


def test_legacy_raw_error_is_sanitized__AC7(client, db, make, auth):
    admin = make.user(admin=True)
    run_id = _insert_run(
        db,
        status="that_bai",
        started_at=datetime(2041, 1, 1, tzinfo=UTC),
        details='{"message":"password=secret host=private"}',
    )

    body = client.get(
        "/admin/catalog/sync-runs",
        params={"source": SOURCE, "status": "that_bai", "limit": 100},
        headers=auth(admin),
    ).json()
    item = next(item for item in body["items"] if item["id"] == run_id)

    assert item["error_details"] == {
        "code": "sync_failed",
        "message": "Catalog synchronization failed",
    }
    assert "secret" not in str(item)
