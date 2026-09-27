"""Kiểm tra 1 file .env (local hoặc production) có kết nối được Supabase thật không.

Chạy: python scripts/test_env_connection.py .env.production
      python scripts/test_env_connection.py .env.worker.production
      python scripts/test_env_connection.py .env          (local, mặc định)

Chỉ in ra OK/FAIL — không in bất kỳ secret nào ra màn hình.
"""

import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import create_engine, text


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def mask_url(url: str) -> str:
    """In host/port/db, che scheme+user+password."""
    parts = urlsplit(url)
    host_part = parts.hostname or "?"
    port_part = f":{parts.port}" if parts.port else ""
    return f"***:***@{host_part}{port_part}{parts.path}"


def check_database(env: dict[str, str]) -> bool:
    url = env.get("DATABASE_URL", "")
    if not url:
        print("[DATABASE_URL] FAIL — biến rỗng hoặc không tồn tại")
        return False
    print(f"[DATABASE_URL] Đang thử kết nối tới {mask_url(url)} ...")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            who = conn.execute(text("SELECT current_user")).scalar()
            n_tables = conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ).scalar()
        print(f"[DATABASE_URL] OK — đăng nhập bằng role '{who}', thấy {n_tables} bảng trong public")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[DATABASE_URL] FAIL — {type(exc).__name__}: {exc}")
        return False


def check_supabase_auth(env: dict[str, str]) -> bool:
    base = env.get("SUPABASE_URL", "").rstrip("/")
    anon_key = env.get("SUPABASE_ANON_KEY", "")
    if not base or not anon_key:
        print("[SUPABASE_URL/ANON_KEY] FAIL — thiếu biến")
        return False
    parts = urlsplit(base)
    safe_base = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    print(f"[Supabase Auth] Đang gọi thử {safe_base}/auth/v1/health ...")
    try:
        r = httpx.get(f"{base}/auth/v1/health", headers={"apikey": anon_key}, timeout=10)
        ok = r.status_code == 200
        print(f"[Supabase Auth] {'OK' if ok else 'FAIL'} — HTTP {r.status_code}")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[Supabase Auth] FAIL — {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    env_file = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not env_file.exists():
        print(f"Không tìm thấy file: {env_file}")
        sys.exit(1)

    print(f"=== Kiểm tra {env_file} ===\n")
    env = load_env_file(env_file)

    db_ok = check_database(env)
    print()
    auth_ok = check_supabase_auth(env)

    print("\n=== Kết quả ===")
    print(f"Database : {'OK' if db_ok else 'FAIL'}")
    print(f"Auth API : {'OK' if auth_ok else 'FAIL'}")
    sys.exit(0 if (db_ok and auth_ok) else 1)


if __name__ == "__main__":
    main()
