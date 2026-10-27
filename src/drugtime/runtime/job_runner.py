"""Component Job Runner: composition root cho các job của Worker.

Nơi duy nhất nối các module với nhau cho luồng nền: inject NotificationPort vào adherence,
và danh sách UserDataEraser (đúng thứ tự FK, schema v9) vào consent.
"""

import logging
import socket
from uuid import UUID

from drugtime import notification_gateway
from drugtime.modules.adherence import api as adherence
from drugtime.modules.ai_meal import api as ai_meal
from drugtime.modules.catalog import api as catalog
from drugtime.modules.consent import api as consent
from drugtime.modules.family import api as family
from drugtime.modules.health import api as health
from drugtime.modules.identity import api as identity
from drugtime.modules.interaction import api as interaction
from drugtime.modules.medication import api as medication
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work

log = logging.getLogger(__name__)

# Thứ tự xóa theo phụ thuộc FK (schema v9, "Quy trình xóa dữ liệu", bước A).
ERASURE_ORDER = [
    ai_meal.eraser,
    interaction.eraser,
    adherence.eraser,
    medication.eraser,
    family.eraser,
    identity.eraser,
]


def tick() -> None:
    """Chạy mỗi TICK_INTERVAL_SECONDS. Mỗi phần độc lập: một phần lỗi không chặn phần khác."""
    for name, step in (
        ("missed_dose_scan", _scan),
        ("catalog_sync_if_due", _sync_if_due),
        ("resume_erasures", _resume_erasures),
    ):
        try:
            step()
        except Exception:
            log.exception("tick step %s failed", name)


def record_worker_heartbeat(instance_id: str | None = None) -> None:
    health.record_heartbeat(instance_id or socket.gethostname())


def run_erasure(request_id: str) -> None:
    consent.execute_erasure(
        UUID(request_id),
        erasers=ERASURE_ORDER,
        account_remover=identity.account_remover,
        uow_factory=unit_of_work,
    )


_notifier: adherence.NotificationPort | None = None


def validate_notification_config() -> None:
    """Gọi khi Worker khởi động: thiếu hoặc hỏng credential FCM thì dừng ngay với lỗi rõ ràng
    (NotificationConfigError), không chạy lượt quét mà không gửi được push."""
    _gateway()


def _gateway() -> adherence.NotificationPort:
    # Dùng lại giữa các tick để giữ access token FCM còn hạn và kết nối HTTP.
    global _notifier
    if _notifier is None:
        _notifier = notification_gateway.build(get_settings())
    return _notifier


def _scan() -> None:
    count = adherence.scan_missed_doses(unit_of_work, notifier=_gateway())
    log.info("missed-dose scan: %d push alert(s)", count)


def _sync_if_due() -> None:
    catalog.sync_if_due(unit_of_work)


def _resume_erasures() -> None:
    for request_id in consent.pending_erasure_ids(unit_of_work):
        run_erasure(str(request_id))
