"""Script tạo admin dev chỉ chạy với Supabase/DB local (AC7)."""

import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_dev_admin.py"
LOCAL_SUPABASE = "http://127.0.0.1:54321"
LOCAL_DB = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("create_dev_admin", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_network():
    def handler(request):
        raise AssertionError(f"unexpected network call: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ensure(script, client, **kw):
    args = {
        "supabase_url": LOCAL_SUPABASE,
        "service_key": "service",
        "db_url": LOCAL_DB,
        "client": client,
        **kw,
    }
    return script.ensure_admin("admin@drugtime.local", args.pop("password", "password-123"), **args)


def test_refuses_non_local_supabase_url(script, no_network):
    with pytest.raises(script.RefusedError):
        _ensure(script, no_network, supabase_url="https://wqiyhmtgxukjnqxprkzn.supabase.co")


def test_refuses_non_local_database_url(script, no_network):
    with pytest.raises(script.RefusedError):
        _ensure(
            script,
            no_network,
            db_url="postgresql+psycopg://postgres:x@db.wqiyhmtgxukjnqxprkzn.supabase.co:5432/postgres",
        )


def test_refuses_short_password(script, no_network):
    with pytest.raises(script.RefusedError):
        _ensure(script, no_network, password="short")


def test_main_exits_2_when_not_local(script, monkeypatch, capsys):
    from drugtime.shared.config import get_settings

    monkeypatch.setenv("SUPABASE_URL", "https://wqiyhmtgxukjnqxprkzn.supabase.co")
    get_settings.cache_clear()
    try:
        code = script.main(["--email", "admin@drugtime.local", "--password", "password-123"])
    finally:
        get_settings.cache_clear()

    assert code == 2
    assert "password-123" not in capsys.readouterr().err
