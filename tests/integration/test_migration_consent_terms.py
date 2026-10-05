"""Migration 20261005065417_consent_type_terms (task adhoc-20261003-login-medication-ui-fixes;
wf-db-migration): enum consent_type có thêm terms, api_role ghi được dòng terms."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def api_conn():
    """Kết nối của app (api_role, xem fixture app_settings trong conftest)."""
    from drugtime.shared.db import get_engine

    with get_engine().connect() as c:
        yield c


def test_consent_type_has_terms_last__AC24(db):
    values = db.execute(text("SELECT enum_range(NULL::consent_type)::text[]")).scalar_one()
    assert values == ["health_data", "family_sharing", "ai_meal", "terms"]


def test_api_role_can_insert_and_revoke_terms_row__AC24(api_conn, make):
    user = make.user(consents=())
    with api_conn.begin():
        api_conn.execute(
            text(
                "INSERT INTO user_consents (user_id, consent_type, document_version) "
                "VALUES (:u, 'terms', '2026-10-v1')"
            ),
            {"u": user},
        )
        api_conn.execute(
            text(
                "UPDATE user_consents SET status = 'thu_hoi', revoked_at = clock_timestamp() "
                "WHERE user_id = :u AND consent_type = 'terms'"
            ),
            {"u": user},
        )
    status = api_conn.execute(
        text("SELECT status::text FROM user_consents WHERE user_id = :u"), {"u": user}
    ).scalar_one()
    assert status == "thu_hoi"


def test_one_active_terms_row_per_user_enforced_by_db__AC24(db, make):
    user = make.user(consents=())
    db.execute(
        text(
            "INSERT INTO user_consents (user_id, consent_type, document_version) "
            "VALUES (:u, 'terms', '2026-09-v0')"
        ),
        {"u": user},
    )
    with pytest.raises(DBAPIError) as exc:
        db.execute(
            text(
                "INSERT INTO user_consents (user_id, consent_type, document_version) "
                "VALUES (:u, 'terms', '2026-10-v1')"
            ),
            {"u": user},
        )
    assert "user_consents_one_active_idx" in str(exc.value)


def test_unknown_consent_type_still_rejected(db):
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO user_consents (user_id, consent_type, document_version) "
                "VALUES (:u, 'everything', 'x')"
            ),
            {"u": uuid4()},
        )
