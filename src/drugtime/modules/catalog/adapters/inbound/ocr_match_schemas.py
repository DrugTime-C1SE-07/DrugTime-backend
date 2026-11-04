"""Schemas of POST /catalog/medications/match, matching api_contract/openapi.json (4.13)."""

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.catalog.domain.ocr_match import (
    OcrMatchOutcome,
    OcrMatchReason,
    OcrMatchStatus,
    ScoredCandidate,
)
from drugtime.shared.config import get_settings


def _default_limit() -> int:
    return get_settings().ocr_match_default_limit


class OcrMatchRequest(BaseModel):
    """Văn bản OCR của một lần quét."""

    model_config = ConfigDict(extra="forbid")

    # Line breaks are part of the evidence (4.12 clusters); never strip or normalize here.
    text: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    limit: int = Field(default_factory=_default_limit, ge=1, le=10)


class OcrMatchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    active_ingredient: str | None
    strength_text: str | None
    dosage_form: str | None
    has_active_ingredients: bool
    score: float = Field(ge=0, le=1)

    @classmethod
    def from_domain(cls, c: ScoredCandidate) -> "OcrMatchCandidate":
        m = c.medication
        return cls(
            id=m.id,
            name=m.name,
            active_ingredient=m.active_ingredient,
            strength_text=m.strength_text,
            dosage_form=m.dosage_form,
            has_active_ingredients=m.has_active_ingredients,
            score=c.score,
        )


class OcrMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OcrMatchStatus
    items: list[OcrMatchCandidate] = Field(max_length=10)
    preselected_id: int | None
    suggested_query: str | None = Field(min_length=1, max_length=100)
    reasons: list[OcrMatchReason]

    @classmethod
    def from_domain(cls, o: OcrMatchOutcome) -> "OcrMatchResult":
        return cls(
            status=o.status,
            items=[OcrMatchCandidate.from_domain(c) for c in o.items],
            preselected_id=o.preselected_id,
            suggested_query=o.suggested_query,
            reasons=sorted(o.reasons, key=lambda r: r.value),
        )
