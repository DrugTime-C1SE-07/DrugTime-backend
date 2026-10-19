"""Hạ tầng test tích hợp với Postgres thật (Supabase local).

- App chạy bằng api_role như môi trường thật; kết nối quản trị (postgres) chỉ dùng để dựng
  dữ liệu và kiểm DB.
- Mỗi test tạo người dùng và thuốc danh mục mới (id ngẫu nhiên), nên các test không đụng nhau.
  Không xóa dữ liệu sau test: access_logs chỉ ghi thêm (trigger chặn DELETE) và tham chiếu users.
  Chạy `supabase db reset` để về DB sạch.

Biến môi trường (đều có mặc định cho Supabase local):
  TEST_ADMIN_DATABASE_URL  kết nối quản trị, mặc định postgres@127.0.0.1:54322
  TEST_API_ROLE_PASSWORD   mật khẩu đặt cho api_role trên DB local, mặc định "postgres"
"""

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
)
API_PASSWORD = os.environ.get("TEST_API_ROLE_PASSWORD", "postgres")
_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _api_url() -> str:
    url = make_url(ADMIN_URL).set(username="api_role", password=API_PASSWORD)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def admin_engine():
    if make_url(ADMIN_URL).host not in _LOCAL_HOSTS:
        pytest.exit("Integration tests only run against a local database", returncode=2)
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as c:
            # api_role được tạo không có mật khẩu; đặt mật khẩu cho DB local để app đăng nhập.
            c.execute(text(f"ALTER ROLE api_role PASSWORD '{API_PASSWORD}'"))
    except OperationalError as exc:
        pytest.skip(f"Local Supabase is not running ({exc.orig}); run `supabase start`")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def app_settings(admin_engine):
    """Trỏ app vào DB local bằng api_role; secret phiên chỉ dùng cho test."""
    from drugtime.shared.config import get_settings
    from drugtime.shared.db import get_engine

    os.environ["DATABASE_URL"] = _api_url()
    os.environ["SESSION_JWT_SECRET"] = secrets.token_hex(32)
    os.environ["SUPABASE_JWKS_URL"] = ""
    os.environ["SUPABASE_JWT_SECRET"] = secrets.token_hex(32)
    get_settings.cache_clear()
    get_engine.cache_clear()
    with get_engine().connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "api_role"
    yield
    get_engine().dispose()


@pytest.fixture
def db(admin_engine) -> Iterator[Connection]:
    with admin_engine.connect() as c:
        yield c


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    return TestClient(create_app())


def _auth(user_id: UUID) -> dict[str, str]:
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    token = issue_app_session(user_id, SessionType.MOBILE, datetime.now(UTC)).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth():
    """auth(user_id) -> header Authorization với phiên mobile thật."""
    return _auth


@dataclass
class Factory:
    db: Connection

    def user(self, *, admin: bool = False, consents=("health_data",)) -> UUID:
        uid = uuid4()
        self.db.execute(
            text(
                "INSERT INTO users (id, email, full_name, system_role) "
                "VALUES (:id, :email, 'Test User', CAST(:role AS system_role))"
            ),
            {"id": uid, "email": f"{uid}@test.local", "role": "admin" if admin else "user"},
        )
        for purpose in consents:
            self.consent(uid, purpose)
        return uid

    def consent(self, user_id: UUID, purpose: str) -> None:
        self.db.execute(
            text(
                "INSERT INTO user_consents (user_id, consent_type, document_version) "
                "VALUES (:u, CAST(:p AS consent_type), 'test')"
            ),
            {"u": user_id, "p": purpose},
        )

    def revoke_consent(self, user_id: UUID, purpose: str) -> None:
        self.db.execute(
            text(
                "UPDATE user_consents SET status = 'thu_hoi', revoked_at = now() "
                "WHERE user_id = :u AND consent_type = CAST(:p AS consent_type) "
                "AND status = 'dong_y'"
            ),
            {"u": user_id, "p": purpose},
        )

    def link(self, patient_id: UUID, family_id: UUID, *, sharing: bool = True) -> None:
        self.db.execute(
            text(
                "INSERT INTO caregiver_links "
                "(patient_user_id, family_user_id, status, sharing_enabled) "
                "VALUES (:p, :f, 'active', :s)"
            ),
            {"p": patient_id, "f": family_id, "s": sharing},
        )

    def family_of(self, patient_id: UUID, *, sharing: bool = True) -> UUID:
        """Người thân có link active; người bệnh có đủ consent health_data + family_sharing."""
        self.consent(patient_id, "family_sharing")
        family_id = self.user()
        self.link(patient_id, family_id, sharing=sharing)
        return family_id

    def catalog_medication(
        self,
        *,
        with_ingredient: bool = True,
        deleted: bool = False,
        name: str | None = None,
        active_ingredient: str | None = None,
        dosage_form: str | None = "Viên nén",
    ) -> int:
        """`active_ingredient` là medications.raw_active_ingredient (văn bản thô, để hiển thị);
        `with_ingredient` là liên kết hoạt chất chuẩn dùng cho has_interaction_data."""
        mid = self.db.execute(
            text(
                "INSERT INTO medications (name, raw_active_ingredient, strength_text, "
                "dosage_form, deleted_at) "
                "VALUES (:n, :ai, '5 mg', :form, CASE WHEN :d THEN now() END) RETURNING id"
            ),
            {
                "n": name or f"Test drug {uuid4().hex[:8]}",
                "ai": active_ingredient,
                "form": dosage_form,
                "d": deleted,
            },
        ).scalar_one()
        if with_ingredient:
            aid = self.db.execute(
                text(
                    "INSERT INTO active_ingredients (standard_name, role) "
                    "VALUES (:n, 'dieu_tri_benh_nen') RETURNING id"
                ),
                {"n": f"ingredient-{uuid4().hex}"},
            ).scalar_one()
            self.db.execute(
                text(
                    "INSERT INTO medication_active_ingredients (medication_id, "
                    "active_ingredient_id, strength_value, strength_unit, dosing_unit) "
                    "VALUES (:m, :a, 5, 'mg', 'vien')"
                ),
                {"m": mid, "a": aid},
            )
        return mid

    def ingredient(self, *, name: str | None = None, aliases: tuple[str, ...] = ()) -> int:
        """Hoạt chất chuẩn mới (tên ngẫu nhiên nếu không truyền), kèm tên gọi khác."""
        iid = self.db.execute(
            text(
                "INSERT INTO active_ingredients (standard_name, role) "
                "VALUES (:n, 'dieu_tri_benh_nen') RETURNING id"
            ),
            {"n": name or f"ingredient-{uuid4().hex}"},
        ).scalar_one()
        for alias in aliases:
            self.db.execute(
                text(
                    "INSERT INTO ingredient_aliases (active_ingredient_id, alias_text) "
                    "VALUES (:i, :a)"
                ),
                {"i": iid, "a": alias},
            )
        return iid

    def medication_with(self, ingredient_ids: list[int]) -> int:
        """Thuốc danh mục chứa đúng các hoạt chất này (thuốc phối hợp khi nhiều hơn một)."""
        mid = self.catalog_medication(with_ingredient=False)
        for iid in ingredient_ids:
            self.db.execute(
                text(
                    "INSERT INTO medication_active_ingredients (medication_id, "
                    "active_ingredient_id, strength_value, strength_unit, dosing_unit) "
                    "VALUES (:m, :a, 5, 'mg', 'vien')"
                ),
                {"m": mid, "a": iid},
            )
        return mid

    def rule_rows(self, table: str, rule_id: int) -> list[dict]:
        """Mọi phiên bản của một quy tắc (task 2.16), theo version."""
        assert table in ("active_ingredient_interactions", "drug_food_interactions")
        rows = self.db.execute(
            text(f"SELECT * FROM {table} WHERE rule_id = :r ORDER BY version"), {"r": rule_id}
        )
        return [dict(r._mapping) for r in rows]

    def thresholds_of(self, version_id: int) -> list[dict]:
        rows = self.db.execute(
            text(
                "SELECT * FROM active_ingredient_interaction_dose_thresholds "
                "WHERE interaction_id = :v ORDER BY id"
            ),
            {"v": version_id},
        )
        return [dict(r._mapping) for r in rows]

    def counts(self, user_id: UUID) -> dict[str, int]:
        """Số dòng thuốc, lịch, đơn thuốc của một người dùng."""
        row = self.db.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM user_medications WHERE user_id = :u) AS meds, "
                "(SELECT count(*) FROM medication_schedules ms JOIN user_medications um "
                " ON um.id = ms.user_medication_id WHERE um.user_id = :u) AS schedules, "
                "(SELECT count(*) FROM prescriptions WHERE user_id = :u) AS prescriptions"
            ),
            {"u": user_id},
        ).one()
        return dict(row._mapping)

    def schedules(self, user_medication_id: int) -> list[dict]:
        """Mọi lịch (mở và đóng) của một thuốc, theo id."""
        rows = self.db.execute(
            text(
                "SELECT id, to_char(intake_time, 'HH24:MI') AS intake_time, days_of_week, "
                "reminder_enabled, effective_from, ended_at FROM medication_schedules "
                "WHERE user_medication_id = :i ORDER BY id"
            ),
            {"i": user_medication_id},
        )
        return [dict(r._mapping) for r in rows]

    def medication_row(self, user_medication_id: int) -> dict:
        row = self.db.execute(
            text(
                "SELECT quantity_per_dose, doses_per_day, stock_quantity, ended_at, deleted_at "
                "FROM user_medications WHERE id = :i"
            ),
            {"i": user_medication_id},
        ).one()
        return dict(row._mapping)

    def dose_log(self, schedule_id: int, scheduled_at: datetime, status: str = "bo_lo") -> int:
        """Ghi một liều cho lịch (bo_lo không có taken_at; da_uong/uong_tre có taken_at)."""
        return self.db.execute(
            text(
                "INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status) "
                "VALUES (:s, :at, CASE WHEN :st = 'bo_lo' THEN NULL ELSE :at END, "
                "CAST(:st AS dose_status)) RETURNING id"
            ),
            {"s": schedule_id, "at": scheduled_at, "st": status},
        ).scalar_one()

    def dose_logs_of(self, user_medication_id: int) -> list[dict]:
        rows = self.db.execute(
            text(
                "SELECT dl.id, dl.medication_schedule_id, dl.scheduled_at, dl.status::text "
                "AS status FROM dose_logs dl JOIN medication_schedules ms "
                "ON ms.id = dl.medication_schedule_id WHERE ms.user_medication_id = :i "
                "ORDER BY dl.id"
            ),
            {"i": user_medication_id},
        )
        return [dict(r._mapping) for r in rows]

    def access_logs(self, patient_id: UUID) -> list[dict]:
        rows = self.db.execute(
            text(
                "SELECT actor_user_id, actor_role::text AS actor_role, data_scope::text "
                "AS data_scope, result::text AS result, rejection_reason "
                "FROM access_logs WHERE patient_user_id = :p ORDER BY id"
            ),
            {"p": patient_id},
        )
        return [dict(r._mapping) for r in rows]


@pytest.fixture
def make(db) -> Factory:
    return Factory(db)


@pytest.fixture
def admin_auth(make):
    """(admin_id, header) với phiên admin_web thật của một tài khoản admin mới."""
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    admin_id = make.user(admin=True, consents=())
    token = issue_app_session(admin_id, SessionType.ADMIN_WEB, datetime.now(UTC)).token
    return admin_id, {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def role_engines(admin_engine, app_settings):
    """Engine đăng nhập bằng api_role và worker_role (giao dịch thật) để kiểm grant/trigger.
    Chỉ đặt mật khẩu trên DB local, như app_settings làm với api_role."""
    from drugtime.shared.db import get_engine

    with admin_engine.connect() as c:
        c.execute(text(f"ALTER ROLE worker_role WITH LOGIN PASSWORD '{API_PASSWORD}'"))
    worker_url = make_url(ADMIN_URL).set(username="worker_role", password=API_PASSWORD)
    worker = create_engine(worker_url.render_as_string(hide_password=False))
    yield {"api_role": get_engine(), "worker_role": worker}
    worker.dispose()


def _scheduled_body(medication_id: int, **kw) -> dict:
    return {
        "client_uuid": str(uuid4()),
        "medication_id": medication_id,
        "quantity_per_dose": 1,
        "dosing_mode": "scheduled",
        "intake_times": ["08:00", "20:00"],
        **kw,
    }


def _as_needed_body(medication_id: int, **kw) -> dict:
    return {
        "client_uuid": str(uuid4()),
        "medication_id": medication_id,
        "quantity_per_dose": 1,
        "dosing_mode": "as_needed",
        "max_doses_per_day": 3,
        **kw,
    }


@pytest.fixture
def scheduled_body():
    return _scheduled_body


@pytest.fixture
def as_needed_body():
    return _as_needed_body


@pytest.fixture
def wait_for_lock_waiters(db):
    """wait_for_lock_waiters(n): chờ tới khi có `n` phiên api_role đang chờ khóa DB, để hai
    request chắc chắn chạy chồng nhau (không dùng sleep cố định)."""
    import time

    def wait(n: int, deadline_s: float = 20.0) -> None:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            waiting = db.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE usename = 'api_role' "
                    "AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
            if waiting >= n:
                return
        raise AssertionError(f"không thấy {n} request chờ khóa trong {deadline_s}s")

    return wait
