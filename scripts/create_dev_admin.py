"""Tạo (hoặc cập nhật) tài khoản quản trị trên Supabase LOCAL để thử Admin Web.

Chạy (từ thư mục backend/, sau `supabase start`):
    python scripts/create_dev_admin.py --email admin@drugtime.local --password '<ít nhất 8 ký tự>'

Đọc SUPABASE_URL và SUPABASE_SERVICE_KEY từ môi trường/.env (như app), kết nối DB quản trị qua
ADMIN_DATABASE_URL (mặc định postgres@127.0.0.1:54322). Từ chối chạy nếu Supabase hoặc DB không
phải localhost: trên môi trường thật, admin được tạo thủ công. Không in mật khẩu hay key.
"""

import argparse
import os
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEFAULT_ADMIN_DB_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MIN_PASSWORD_LENGTH = 8


class RefusedError(Exception):
    """Điều kiện an toàn không thỏa; script dừng trước khi gọi mạng hay DB."""


def check_local(supabase_url: str, db_url: str) -> None:
    if urlsplit(supabase_url).hostname not in LOCAL_HOSTS:
        raise RefusedError("SUPABASE_URL is not local; create admins on hosted projects manually")
    if make_url(db_url).host not in LOCAL_HOSTS:
        raise RefusedError("ADMIN_DATABASE_URL is not local")


def ensure_admin(
    email: str,
    password: str,
    *,
    supabase_url: str,
    service_key: str,
    db_url: str,
    client: httpx.Client | None = None,
) -> UUID:
    """Đảm bảo có user Supabase với mật khẩu này và dòng `users` có system_role = admin."""
    check_local(supabase_url, db_url)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RefusedError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    email = email.strip().lower()
    http = client or httpx.Client(timeout=10)
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    base = f"{supabase_url}/auth/v1/admin/users"

    engine = create_engine(db_url)
    try:
        with engine.begin() as c:
            existing = c.execute(
                text("SELECT id FROM auth.users WHERE lower(email) = :e"), {"e": email}
            ).scalar()
            if existing is None:
                r = http.post(
                    base,
                    headers=headers,
                    json={"email": email, "password": password, "email_confirm": True},
                )
                r.raise_for_status()
                user_id = UUID(r.json()["id"])
            else:
                user_id = UUID(str(existing))
                r = http.put(f"{base}/{user_id}", headers=headers, json={"password": password})
                r.raise_for_status()
            c.execute(
                text(
                    "INSERT INTO users (id, email, full_name, system_role) "
                    "VALUES (:id, :email, 'Quản trị viên', 'admin') "
                    "ON CONFLICT (id) DO UPDATE SET system_role = 'admin', email = EXCLUDED.email"
                ),
                {"id": user_id, "email": email},
            )
    finally:
        engine.dispose()
    return user_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args(argv)

    from drugtime.shared.config import get_settings

    settings = get_settings()
    db_url = os.environ.get("ADMIN_DATABASE_URL", DEFAULT_ADMIN_DB_URL)
    try:
        user_id = ensure_admin(
            args.email,
            args.password,
            supabase_url=settings.supabase_url,
            service_key=settings.supabase_service_key,
            db_url=db_url,
        )
    except RefusedError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPStatusError as exc:
        print(f"Supabase Auth returned {exc.response.status_code}", file=sys.stderr)
        return 1
    print(f"Admin ready: {args.email.strip().lower()} ({user_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
