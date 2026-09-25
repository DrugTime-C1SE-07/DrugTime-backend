import logging

from drugtime.modules.adherence.api import Alert

log = logging.getLogger(__name__)


class FcmGateway:
    """FCM HTTP v1. Best effort: lỗi từng token được log, không làm hỏng lượt quét."""

    def __init__(self, project_id: str) -> None:
        self._url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    def send(self, alerts: list[Alert]) -> None:
        for alert in alerts:
            try:
                self._send_one(alert)
            except Exception:
                log.exception("FCM send failed for notification %s", alert.notification_id)

    def _send_one(self, alert: Alert) -> None:
        # Payload chỉ gồm câu báo chung + notification_id (không có tên thuốc, giờ uống).
        # TODO: lấy OAuth2 access token từ service account và POST tới self._url.
        raise NotImplementedError
