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
                log.exception("FCM send failed for notification %s", alert.notification_id)

    def _send_one(self, alert: Alert) -> None:
        payload = build_fcm_payload(alert)
        if not self._project_id:
            log.info("FCM simulated send (no project_id): token=%s", alert.device_token)
            return
        log.info("FCM dispatching to %s: %s", alert.device_token, payload)
