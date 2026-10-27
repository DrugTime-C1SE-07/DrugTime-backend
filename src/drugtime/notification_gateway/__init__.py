"""Component Notification Gateway: hiện thực NotificationPort của adherence (CD8, QA.11).

Thêm kênh mới (vd Zalo OA) = thêm một adapter ở đây + một nhánh trong build().
"""

import httpx

from drugtime.modules.adherence.api import NotificationPort
from drugtime.notification_gateway.fcm import FcmGateway
from drugtime.notification_gateway.fcm_auth import (
    AccessTokenProvider,
    NotificationConfigError,
    load_service_account,
)
from drugtime.notification_gateway.mock import MockGateway
from drugtime.shared.config import Settings

__all__ = ["NotificationConfigError", "build"]

FCM_TIMEOUT_SECONDS = 10.0


def build(settings: Settings) -> NotificationPort:
    """Kênh fcm thiếu hoặc hỏng credential thì ném NotificationConfigError, không gửi giả."""
    if settings.notification_channel == "fcm":
        if not settings.fcm_credentials_file:
            raise NotificationConfigError(
                "FCM_CREDENTIALS_FILE is required when NOTIFICATION_CHANNEL=fcm"
            )
        account = load_service_account(settings.fcm_credentials_file)
        project_id = settings.fcm_project_id or account.project_id
        if not project_id:
            raise NotificationConfigError("FCM project id is missing")
        client = httpx.Client(timeout=FCM_TIMEOUT_SECONDS)
        return FcmGateway(project_id, AccessTokenProvider(account, client), client)
    return MockGateway()
