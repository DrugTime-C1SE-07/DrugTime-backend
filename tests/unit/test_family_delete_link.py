"""TDD Unit tests for DELETE /links/{id} endpoint (SCRUM-134, Backlog 3.26).

Kiểm tra:
1. Bệnh nhân sở hữu link thu hồi thành công -> 204 No Content.
2. Người thân thuộc link tự rời thành công -> 204 No Content.
3. Người lạ không thuộc link bị từ chối -> 403 {"detail": "khong_co_quyen"}.
4. Link không tồn tại bị từ chối -> 403 {"detail": "khong_co_quyen"}.
5. Link pending được thu hồi thành công -> 204 No Content, status='revoked'.
6. Gỡ lặp lại (idempotent) -> 204 No Content, giữ nguyên revoked_at ban đầu.
7. Thiếu hoặc sai token xác thực -> 401 Unauthorized.
"""
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

if "sqlalchemy" not in sys.modules:
    mock_sa = MagicMock()
    mock_sa.text = lambda sql: sql
    sys.modules["sqlalchemy"] = mock_sa

if "jwt" not in sys.modules:
    sys.modules["jwt"] = MagicMock()

if "pydantic_settings" not in sys.modules:
    mock_ps = MagicMock()
    mock_ps.BaseSettings = object
    mock_ps.SettingsConfigDict = dict
    sys.modules["pydantic_settings"] = mock_ps



import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from drugtime.modules.family.adapters.inbound.http import router as family_router

from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow
from drugtime.shared.errors import DomainError, Forbidden, NotFound, Unauthorized


class MockFakeLinks:
    def __init__(self, links=None):
        self.links = {link.id: link for link in links or []}
        self.revoked_calls = []

    def get(self, uow, link_id: int):
        return self.links.get(link_id)

    def revoke(self, uow, *, link_id: int, caller_id: UUID, now: datetime):
        link = self.links.get(link_id)
        if link is None:
            return None
        if caller_id != link.patient_user_id and caller_id != link.family_user_id:
            return None
        updated = FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.REVOKED,
            sharing_enabled=False,
            linked_at=link.linked_at,
            revoked_at=link.revoked_at or now,
            rejected_at=link.rejected_at,
        )
        self.links[link_id] = updated
        self.revoked_calls.append((link_id, caller_id, now))
        return updated

    def update_status(self, uow, link_id, status, revoked_at, rejected_at):
        link = self.links[link_id]
        updated = FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=status,
            sharing_enabled=False if status == LinkStatus.REVOKED else link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=revoked_at,
            rejected_at=rejected_at,
        )
        self.links[link_id] = updated
        return updated


@pytest.fixture
def test_setup():
    patient_id = uuid4()
    family_id = uuid4()
    stranger_id = uuid4()

    link1 = FamilyLink(1, patient_id, family_id, LinkStatus.ACTIVE, sharing_enabled=True)
    link_pending = FamilyLink(2, patient_id, family_id, LinkStatus.PENDING, sharing_enabled=False)
    initial_revoked_at = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    link_revoked = FamilyLink(
        3, patient_id, family_id, LinkStatus.REVOKED, sharing_enabled=False, revoked_at=initial_revoked_at
    )

    fake_links = MockFakeLinks([link1, link_pending, link_revoked])

    app = FastAPI()
    app.include_router(family_router)

    # Exception handlers tương tự drugtime.main
    @app.exception_handler(Forbidden)
    def forbidden_handler(_: Request, exc: Forbidden):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(Unauthorized)
    def unauthorized_handler(_: Request, exc: Unauthorized):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.exception_handler(NotFound)
    def not_found_handler(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(DomainError)
    def domain_error_handler(_: Request, exc: DomainError):
        return JSONResponse({"detail": str(exc)}, status_code=422)


    # Mock SqlLinks() inside http.py using monkeypatch or fake_links
    import drugtime.modules.family.adapters.inbound.http as http_module

    original_sqllinks = http_module.SqlLinks
    http_module.SqlLinks = lambda: fake_links

    yield {
        "app": app,
        "fake_links": fake_links,
        "patient_id": patient_id,
        "family_id": family_id,
        "stranger_id": stranger_id,
        "initial_revoked_at": initial_revoked_at,
    }

    http_module.SqlLinks = original_sqllinks


def test_http_patient_revokes_active_link_204(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/1")

    assert res.status_code == 204
    assert res.text == ""

    link = test_setup["fake_links"].links[1]
    assert link.status is LinkStatus.REVOKED
    assert link.sharing_enabled is False
    assert link.revoked_at is not None


def test_http_family_member_self_leave_204(test_setup):
    app = test_setup["app"]
    family_id = test_setup["family_id"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=family_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/1")

    assert res.status_code == 204
    assert res.text == ""

    link = test_setup["fake_links"].links[1]
    assert link.status is LinkStatus.REVOKED
    assert link.sharing_enabled is False
    assert link.revoked_at is not None


def test_http_stranger_cannot_revoke_returns_403(test_setup):
    app = test_setup["app"]
    stranger_id = test_setup["stranger_id"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=stranger_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/1")

    assert res.status_code == 403
    assert res.json() == {"detail": "khong_co_quyen"}


def test_http_non_existent_link_returns_403(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/9999")

    assert res.status_code == 403
    assert res.json() == {"detail": "khong_co_quyen"}


def test_http_pending_link_revoked_204(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/2")

    assert res.status_code == 204

    link = test_setup["fake_links"].links[2]
    assert link.status is LinkStatus.REVOKED
    assert link.sharing_enabled is False
    assert link.revoked_at is not None


def test_http_already_revoked_is_idempotent_204(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]
    initial_revoked_at = test_setup["initial_revoked_at"]

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/3")

    assert res.status_code == 204

    link = test_setup["fake_links"].links[3]
    assert link.status is LinkStatus.REVOKED
    assert link.revoked_at == initial_revoked_at  # không bị ghi đè!


def test_http_missing_token_returns_401(test_setup):
    app = test_setup["app"]
    app.dependency_overrides[get_uow] = lambda: object()
    # Không override identity.current_user -> gọi logic thật, thiếu Authorization header -> 401

    client = TestClient(app)
    res = client.delete("/links/1")

    assert res.status_code == 401
    assert res.json() == {"detail": "Missing bearer token"}


def test_http_rejected_link_returns_422(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]
    family_id = test_setup["family_id"]

    link_rejected = FamilyLink(4, patient_id, family_id, LinkStatus.REJECTED)
    test_setup["fake_links"].links[4] = link_rejected

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/4")

    assert res.status_code == 422
    assert res.json() == {"detail": "cannot transition family link from rejected to revoked"}



def test_http_old_route_returns_404(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]
    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )
    client = TestClient(app)
    res = client.delete("/family/links/1")
    assert res.status_code == 404


def test_http_already_revoked_with_sharing_enabled_true_clears_sharing_204(test_setup):
    app = test_setup["app"]
    patient_id = test_setup["patient_id"]
    family_id = test_setup["family_id"]
    initial_revoked_at = test_setup["initial_revoked_at"]

    link_revoked_sharing = FamilyLink(
        5,
        patient_id,
        family_id,
        LinkStatus.REVOKED,
        sharing_enabled=True,
        revoked_at=initial_revoked_at,
    )
    test_setup["fake_links"].links[5] = link_revoked_sharing

    app.dependency_overrides[get_uow] = lambda: object()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=patient_id, is_admin=False
    )

    client = TestClient(app)
    res = client.delete("/links/5")

    assert res.status_code == 204

    link = test_setup["fake_links"].links[5]
    assert link.status is LinkStatus.REVOKED
    assert link.sharing_enabled is False
    assert link.revoked_at == initial_revoked_at
