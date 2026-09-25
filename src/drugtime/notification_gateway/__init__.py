"""Component Notification Gateway: hiện thực NotificationPort của adherence (CD8, QA.11).

Thêm kênh mới (vd Zalo OA) = thêm một adapter ở đây + một nhánh trong build().
"""

from drugtime.modules.adherence.api import NotificationPort
from drugtime.notification_gateway.fcm import FcmGateway
from drugtime.notification_gateway.mock import MockGateway
from drugtime.shared.config import Settings


def build(settings: Settings) -> NotificationPort:
    if settings.notification_channel == "fcm":
        return FcmGateway(settings.fcm_project_id)
    return MockGateway()
