"""Task 3.19 (P16, P17): FCM HTTP v1 thật với máy chủ giả (httpx.MockTransport), RS256 thật."""

import json
import logging
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from drugtime import notification_gateway
from drugtime.modules.adherence.domain.alert import Alert, SyncRequest
from drugtime.notification_gateway.fcm import FcmGateway
from drugtime.notification_gateway.fcm_auth import (
    AccessTokenProvider,
    NotificationConfigError,
    ServiceAccount,
)
from drugtime.notification_gateway.mock import MockGateway
from drugtime.shared.config import Settings

TOKEN_URI = "https://oauth2.example.test/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/drugtime-test/messages:send"


@pytest.fixture(scope="module")
def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@pytest.fixture
def account(key_pair):
    return ServiceAccount(
        "worker@drugtime-test.iam.example", key_pair[0], TOKEN_URI, "drugtime-test"
    )


class FakeFcm:
    """Máy chủ token + FCM giả; ghi lại mọi request."""

    def __init__(self, send_status=None):
        self.token_requests = []
        self.sends = []
        self.send_status = send_status or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            self.token_requests.append(parse_qs(request.content.decode()))
            n = len(self.token_requests)
            return httpx.Response(200, json={"access_token": f"access-{n}", "expires_in": 3600})
        assert str(request.url) == SEND_URL
        body = json.loads(request.content)
        self.sends.append((request.headers["authorization"], body))
        token = body["message"]["token"]
        status = self.send_status.get(token, 200)
        if status == 404:
            return httpx.Response(
                404,
                json={
                    "error": {
                        "code": 404,
                        "message": f"Requested entity was not found: {token}",
                        "status": "NOT_FOUND",
                        "details": [{"errorCode": "UNREGISTERED"}],
                    }
                },
            )
        if status != 200:
            return httpx.Response(
                status, json={"error": {"message": f"bad {token}", "details": []}}
            )
        return httpx.Response(200, json={"name": "projects/drugtime-test/messages/1"})


def gateway(account, fake, clock=lambda: 1_000_000.0):
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return FcmGateway("drugtime-test", AccessTokenProvider(account, client, clock), client)


def test_alert_payload_v1__AC42(account, key_pair):
    fake = FakeFcm()
    alert = Alert(notification_id=42, recipient_id=uuid4(), device_token="family-token")

    assert gateway(account, fake).send([alert]) == []

    authorization, body = fake.sends[0]
    assert authorization == "Bearer access-1"
    assert body == {
        "message": {
            "token": "family-token",
            "notification": {"title": "DrugTime", "body": "Bạn có cảnh báo mới về người thân"},
            "android": {
                "notification": {
                    "visibility": "PRIVATE",
                    "channel_id": "family_alerts",
                    "tag": "family_alert_42",
                }
            },
            "data": {"notification_id": "42"},
        }
    }
    # Assertion JWT ký RS256 bằng khóa service account, đúng scope và aud.
    grant = fake.token_requests[0]
    assert grant["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    claims = jwt.decode(
        grant["assertion"][0],
        key_pair[1],
        algorithms=["RS256"],
        audience=TOKEN_URI,
        options={"verify_exp": False, "verify_iat": False},  # đồng hồ giả cố định
    )
    assert claims["iss"] == account.client_email
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert claims["exp"] - claims["iat"] == 3600


def test_sync_request_payload_data_only_high_priority__AC37(account):
    fake = FakeFcm()

    gateway(account, fake).request_sync([SyncRequest(uuid4(), "patient-android")])

    assert fake.sends[0][1] == {
        "message": {
            "token": "patient-android",
            "data": {"type": "sync_request"},
            "android": {"priority": "HIGH", "collapse_key": "sync_request"},
        }
    }
    assert "notification" not in fake.sends[0][1]["message"]


def test_unregistered_token_returned__AC42(account):
    fake = FakeFcm({"gone": 404, "ok": 200})
    gw = gateway(account, fake)

    alerts = [Alert(1, uuid4(), "gone"), Alert(2, uuid4(), "ok")]
    assert gw.send(alerts) == ["gone"]
    assert gw.request_sync([SyncRequest(uuid4(), "gone"), SyncRequest(uuid4(), "ok")]) == ["gone"]


def test_errors_logged_without_token_or_payload__AC42(account, caplog):
    fake = FakeFcm({"secret-token-a": 500, "secret-token-b": 403})
    gw = gateway(account, fake)
    caplog.set_level(logging.INFO)

    assert gw.send([Alert(7, uuid4(), "secret-token-a")]) == []
    assert gw.request_sync([SyncRequest(uuid4(), "secret-token-b")]) == []

    assert "notification 7: HTTP 500" in caplog.text
    assert "sync_request: HTTP 403" in caplog.text
    for secret in ("secret-token-a", "secret-token-b", "access-1", "Bạn có", 'sync_request"}'):
        assert secret not in caplog.text


def test_transport_error_logs_only_error_type(account, caplog):
    def broken(request):
        raise httpx.ConnectError(f"cannot reach {request.url} for secret-token", request=request)

    client = httpx.Client(transport=httpx.MockTransport(broken))
    gw = FcmGateway("drugtime-test", AccessTokenProvider(account, client), client)

    assert gw.send([Alert(9, uuid4(), "secret-token")]) == []
    assert "notification 9: ConnectError" in caplog.text
    assert "secret-token" not in caplog.text


def test_access_token_cached_until_expiry__AC42(account):
    fake = FakeFcm()
    now = [1_000_000.0]
    gw = gateway(account, fake, clock=lambda: now[0])

    gw.send([Alert(1, uuid4(), "t")])
    now[0] += 3600 - 61
    gw.send([Alert(2, uuid4(), "t")])
    assert len(fake.token_requests) == 1

    now[0] += 2  # trong khoảng 60 giây trước khi hết hạn: lấy token mới
    gw.send([Alert(3, uuid4(), "t")])
    assert len(fake.token_requests) == 2
    assert fake.sends[-1][0] == "Bearer access-2"


def test_unauthorized_send_refreshes_token_next_time(account):
    fake = FakeFcm({"t": 401})
    gw = gateway(account, fake)

    gw.send([Alert(1, uuid4(), "t")])
    gw.send([Alert(2, uuid4(), "t")])

    assert len(fake.token_requests) == 2


def _settings(**kw):
    return Settings(_env_file=None, **kw)


def test_missing_credentials_raise_config_error__AC42(tmp_path):
    with pytest.raises(NotificationConfigError, match="FCM_CREDENTIALS_FILE is required"):
        notification_gateway.build(_settings(notification_channel="fcm"))

    broken = tmp_path / "sa.json"
    broken.write_text('{"private_key": "-----BEGIN PRIVATE KEY-----secret"}', encoding="utf-8")
    with pytest.raises(NotificationConfigError) as exc:
        notification_gateway.build(
            _settings(notification_channel="fcm", fcm_credentials_file=str(broken))
        )
    assert "secret" not in str(exc.value)

    with pytest.raises(NotificationConfigError):
        notification_gateway.build(
            _settings(notification_channel="fcm", fcm_credentials_file=str(tmp_path / "none.json"))
        )


def test_build_uses_project_from_service_account(tmp_path, key_pair):
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            {
                "client_email": "worker@drugtime-test.iam.example",
                "private_key": key_pair[0],
                "token_uri": TOKEN_URI,
                "project_id": "drugtime-test",
            }
        ),
        encoding="utf-8",
    )

    gw = notification_gateway.build(
        _settings(notification_channel="fcm", fcm_credentials_file=str(path))
    )

    assert isinstance(gw, FcmGateway)
    assert gw._url == SEND_URL
    assert isinstance(notification_gateway.build(_settings()), MockGateway)
