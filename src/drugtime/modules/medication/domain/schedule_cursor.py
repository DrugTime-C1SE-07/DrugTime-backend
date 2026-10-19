"""Con trỏ trang của GET /patients/{patient_id}/schedules (task 2.04). Hàm thuần, không I/O.

Con trỏ là base64url của JSON {"p": patient_id, "a": id lịch cuối của trang trước}. Không ký:
nó chỉ chọn vị trí trong dữ liệu mà người gọi đã được phép đọc; quyền kiểm riêng ở mỗi request.
"""

import base64
import binascii
import json
from uuid import UUID

from drugtime.shared.errors import DomainError

INVALID_CURSOR = "invalid_cursor"


def encode(patient_id: UUID, last_id: int) -> str:
    raw = json.dumps({"p": str(patient_id), "a": last_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str, patient_id: UUID) -> int:
    """Id lịch cuối của trang trước. Con trỏ hỏng hoặc của người bệnh khác: invalid_cursor."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        last_id = data["a"]
        same_patient = UUID(data["p"]) == patient_id
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, KeyError) as e:
        raise DomainError(INVALID_CURSOR) from e
    if not same_patient or type(last_id) is not int or last_id < 0:
        raise DomainError(INVALID_CURSOR)
    return last_id
