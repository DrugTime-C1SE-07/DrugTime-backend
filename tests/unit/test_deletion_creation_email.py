from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from drugtime.modules.consent.adapters.outbound import email_otp
from drugtime.modules.identity.adapters.outbound import supabase_auth
from drugtime.shared.errors import ServiceUnavailable


@pytest.mark.parametrize("verified", [True, False])
def test_auth_provider_returns_only_confirmed_email(monkeypatch, verified):
    account = uuid4()
    monkeypatch.setattr(
        supabase_auth,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://auth.example.test",
            supabase_anon_key="unit-anon",
            supabase_service_key="unit-service",
        ),
    )

    def get(request):
        assert request.method == "GET"
        assert request.url.path == f"/auth/v1/admin/users/{account}"
        assert request.headers["Authorization"] == "Bearer unit-service"
        return httpx.Response(
            200,
            json={
                "id": str(account),
                "email": "member@example.test",
                "email_confirmed_at": "2026-10-01T00:00:00Z" if verified else None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(get)) as client:
        email = supabase_auth.SupabaseAuth(client).verified_email(account)
    assert email == ("member@example.test" if verified else None)


def test_smtp_uses_tls_and_translates_errors_without_returning_provider_data(monkeypatch):
    settings = SimpleNamespace(
        deletion_smtp_host="smtp.example.test",
        deletion_smtp_port=465,
        deletion_smtp_sender="sender@example.test",
        deletion_smtp_username="unit-user",
        deletion_smtp_password="unit-password",
    )
    smtp_ssl = MagicMock()
    monkeypatch.setattr(email_otp, "get_settings", lambda: settings)
    monkeypatch.setattr(email_otp.smtplib, "SMTP_SSL", smtp_ssl)
    smtp = smtp_ssl.return_value.__enter__.return_value
    email_otp.send_deletion_otp("member@example.test", "012345")
    assert smtp_ssl.call_args.kwargs["context"].check_hostname
    smtp.login.assert_called_once_with("unit-user", "unit-password")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "member@example.test"
    assert "012345" in message.get_content()

    smtp.send_message.side_effect = OSError("private SMTP response")
    with pytest.raises(ServiceUnavailable, match="^service_unavailable$"):
        email_otp.send_deletion_otp("member@example.test", "012345")
