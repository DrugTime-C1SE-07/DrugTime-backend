from pydantic import BaseModel, ConfigDict, Field


class ConditionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: int = Field(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})
    name: str


class ConditionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ConditionResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
