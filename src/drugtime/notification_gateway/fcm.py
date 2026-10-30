import logging

import httpx

from drugtime.modules.adherence.api import Alert, SyncRequest
from drugtime.notification_gateway.fcm_auth import AccessTokenProvider

log = logging.getLogger(__name__)


class FcmSendError(RuntimeError):
    """Lỗi FCM có thông điệp an toàn để log: chỉ mã HTTP và mã lỗi FCM."""


def _reason(exc: Exception) -> str:
    # Thông điệp của httpx hay provider có thể chứa token hoặc payload; chỉ log tên lớp lỗi.
    return str(exc) if isinstance(exc, FcmSendError) else type(exc).__name__


def build_fcm_payload(alert: Alert) -> dict:
    """Xây dựng payload FCM HTTP v1 tuân thủ CD6: chỉ có câu báo chung + notification_id."""
    return {
        "message": {
            "token": alert.device_token,
            "notification": {
                "title": alert.title,
                "body": alert.body,
            },
            "android": {
                "notification": {
                    "visibility": "PRIVATE",
                    "channel_id": "family_alerts",
                    "tag": "family_alert_" + str(alert.notification_id),
                }
            },
            # App dùng ID gọi API có kiểm quyền; không đưa snapshot thuốc/giờ vào data.
            "data": {
                "notification_id": str(alert.notification_id),
            },
        }
    }


def build_sync_request_payload(request: SyncRequest) -> dict:
    """Push ẩn gõ cửa (contract POST /doses/sync-checkpoints): data message, không có khối
    notification nên không hiện gì; collapse_key để máy offline chỉ nhận một push khi có mạng."""
    return {
        "message": {
            "token": request.device_token,
            "data": {"type": "sync_request"},
            "android": {"priority": "HIGH", "collapse_key": "sync_request"},
        }
    }


class FcmGateway:
    """FCM HTTP v1. Best effort: lỗi từng token được log, không làm hỏng lượt quét.
    Trả các token FCM báo UNREGISTERED để adherence gỡ khỏi device_tokens."""

    def __init__(self, project_id: str, tokens: AccessTokenProvider, client: httpx.Client) -> None:
        self._url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        self._tokens = tokens
        self._client = client

    def send(self, alerts: list[Alert]) -> list[str]:
        unregistered = []
        for alert in alerts:
            try:
                if self._send_one(alert):
                    unregistered.append(alert.device_token)
            except Exception as exc:
                log.error(
                    "FCM send failed for notification %s: %s", alert.notification_id, _reason(exc)
                )
        return unregistered

    def request_sync(self, requests: list[SyncRequest]) -> list[str]:
        unregistered = []
        for request in requests:
            try:
                if self._post(build_sync_request_payload(request)):
                    unregistered.append(request.device_token)
            except Exception as exc:
                log.error("FCM send failed for sync_request: %s", _reason(exc))
        return unregistered

    def _send_one(self, alert: Alert) -> bool:
        return self._post(build_fcm_payload(alert))

    def _post(self, payload: dict) -> bool:
        """True khi token không còn đăng ký (404 UNREGISTERED); lỗi khác ném để caller log."""
        response = self._client.post(
            self._url, json=payload, headers={"Authorization": f"Bearer {self._tokens.token()}"}
        )
        if response.status_code == 200:
            return False
        if response.status_code == 401:
            self._tokens.invalidate()  # lần gửi sau lấy access token mới
        if response.status_code == 404 and _error_code(response) == "UNREGISTERED":
            return True
        raise FcmSendError(f"HTTP {response.status_code} {_error_code(response) or ''}".strip())


def _error_code(response: httpx.Response) -> str | None:
    # Chỉ đọc mã lỗi của FCM; không đưa thông điệp lỗi (có thể chứa token) vào log.
    try:
        details = response.json()["error"].get("details", [])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    for detail in details:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])
    return None
