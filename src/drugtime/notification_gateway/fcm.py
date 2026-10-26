import logging

from drugtime.modules.adherence.api import Alert

log = logging.getLogger(__name__)


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


class FcmGateway:
    """FCM HTTP v1. Best effort: lỗi từng token được log, không làm hỏng lượt quét."""

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self._url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    def send(self, alerts: list[Alert]) -> None:
        for alert in alerts:
            try:
                self._send_one(alert)
            except Exception:
                # Provider exception text can contain a token or the request payload.
                log.error("FCM send failed for notification %s", alert.notification_id)

    # Điểm gửi hiện còn stub: dựng payload và ghi log, chưa thực hiện HTTP tới FCM.
    def _send_one(self, alert: Alert) -> None:
        build_fcm_payload(alert)
        if not self._project_id:
            log.info("FCM simulated send (no project_id)")
            return
        log.info("FCM dispatch requested for notification %s", alert.notification_id)
