"""Response của /family, khớp api_contract/openapi.json (task 3.10)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.family.domain.link_code import LinkCode as LinkCodeRecord

_CODE = "[A-HJKMNP-Z2-9]{10}"


class LinkCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(pattern=f"^{_CODE}$", min_length=10, max_length=10)]
    qr_payload: Annotated[str, Field(pattern=rf"^drugtime://link\?code={_CODE}$")]

    @classmethod
    def from_record(cls, record: LinkCodeRecord) -> "LinkCode":
        return cls(code=record.code, qr_payload=record.qr_payload)


class ErrorDetail(BaseModel):
    detail: str
