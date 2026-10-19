"""Request/response của /family, khớp api_contract/openapi.json (task 3.10, 3.13)."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr

from drugtime.modules.family.domain.link import FamilyLink
from drugtime.modules.family.domain.link_code import LinkCode as LinkCodeRecord
from drugtime.shared.config import get_settings

_CODE = "[A-HJKMNP-Z2-9]{10}"
_CODE_RE = re.compile(f"^{_CODE}$")


def _normalize_code(value: str) -> str:
    """Bỏ khoảng trắng hai đầu, đổi chữ hoa rồi mới kiểm định dạng (mã nhập tay).

    Message lỗi không chứa mã: mã là bí mật cấp quyền gửi yêu cầu (QD-04).
    """
    code = value.strip().upper()
    if not _CODE_RE.match(code):
        raise ValueError("code must be 10 characters from A-H J K M N P-Z 2-9")
    return code


LinkCodeInput = Annotated[
    StrictStr, Field(min_length=1, max_length=32), AfterValidator(_normalize_code)
]


class LinkCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(pattern=f"^{_CODE}$", min_length=10, max_length=10)]
    qr_payload: Annotated[str, Field(pattern=rf"^drugtime://link\?code={_CODE}$")]

    @classmethod
    def from_record(cls, record: LinkCodeRecord) -> "LinkCode":
        return cls(code=record.code, qr_payload=record.qr_payload)


class ErrorDetail(BaseModel):
    detail: str


class LinkRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: UUID
    code: LinkCodeInput


class LinkRequest(BaseModel):
    """Yêu cầu liên kết; không có thông tin hồ sơ người bệnh (QD-34 (b))."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[int, Field(json_schema_extra={"format": "int64"})]
    status: Literal["pending", "active", "rejected", "revoked"]
    requested_at: datetime

    @classmethod
    def from_record(cls, link: FamilyLink) -> "LinkRequest":
        return cls(
            id=link.id,
            status=link.status.value,
            requested_at=link.linked_at.astimezone(ZoneInfo(get_settings().timezone)),
        )
