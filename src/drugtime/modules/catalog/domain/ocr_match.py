"""Values and pure rules for matching one OCR scan against the catalog (task 4.13).

Nothing here selects a medicine for the user: the outcome is a suggestion that the
user must confirm (QD-39).
"""

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from drugtime.modules.catalog.domain.catalog_index import StrengthEvidence
from drugtime.modules.catalog.domain.medication import CatalogMedication


class OcrMatchStatus(StrEnum):
    MATCHED = "matched"
    LOW_CONFIDENCE = "low_confidence"
    NO_MATCH = "no_match"


class OcrMatchReason(StrEnum):
    STRENGTH_UNVERIFIED = "strength_unverified"
    STRENGTH_UNPARSED = "strength_unparsed"
    MULTIPLE_STRENGTHS = "multiple_strengths"
    STRENGTH_CONFLICT = "strength_conflict"
    STRENGTH_MISMATCH = "strength_mismatch"
    LASA_CLOSE = "lasa_close"
    TIE = "tie"
    TRUNCATED = "truncated"
    BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    """Thresholds and weights; validated once so a bad config fails at startup of a call."""

    threshold: float = 0.7
    low_threshold: float = 0.4
    margin: float = 0.05
    default_limit: int = 5
    weight_name: float = 0.5
    weight_strength: float = 0.3
    weight_ingredient: float = 0.15
    weight_vote: float = 0.05
    fuzzy_similarity: float = 0.3
    fuzzy_limit: int = 50
    ingredient_line_similarity: float = 0.6

    def __post_init__(self) -> None:
        for name in (
            "threshold",
            "low_threshold",
            "margin",
            "fuzzy_similarity",
            "ingredient_line_similarity",
        ):
            value = getattr(self, name)
            if not (math.isfinite(value) and 0 <= value <= 1):
                raise ValueError(f"OCR match {name} must be within [0, 1]")
        if self.low_threshold > self.threshold:
            raise ValueError("OCR match low_threshold must not exceed threshold")
        weights = self.weights
        if any(not math.isfinite(w) or w < 0 for w in weights):
            raise ValueError("OCR match weights must be non-negative")
        if abs(sum(weights) - 1) > 1e-9:
            raise ValueError("OCR match weights must sum to 1")
        if not 1 <= self.default_limit <= 10:
            raise ValueError("OCR match default_limit must be within 1..10")
        if self.fuzzy_limit < 1:
            raise ValueError("OCR match fuzzy_limit must be positive")

    @property
    def weights(self) -> tuple[float, float, float, float]:
        return (self.weight_name, self.weight_strength, self.weight_ingredient, self.weight_vote)

    @classmethod
    def from_settings(cls, settings) -> "MatchPolicy":
        return cls(
            threshold=settings.ocr_match_threshold,
            low_threshold=settings.ocr_match_low_threshold,
            margin=settings.ocr_match_margin,
            default_limit=settings.ocr_match_default_limit,
            weight_name=settings.ocr_match_weight_name,
            weight_strength=settings.ocr_match_weight_strength,
            weight_ingredient=settings.ocr_match_weight_ingredient,
            weight_vote=settings.ocr_match_weight_vote,
            fuzzy_similarity=settings.ocr_match_fuzzy_similarity,
            fuzzy_limit=settings.ocr_match_fuzzy_limit,
            ingredient_line_similarity=settings.ocr_match_ingredient_line_similarity,
        )


@dataclass(frozen=True, slots=True)
class FuzzyHit:
    """A medication found by trigram similarity for an OCR name key with no substring hit."""

    medication: CatalogMedication
    query_key: str
    cluster_id: int
    line_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FuzzyLookup:
    hits: tuple[FuzzyHit, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    medication: CatalogMedication
    score: float


@dataclass(frozen=True, slots=True)
class OcrMatchOutcome:
    status: OcrMatchStatus
    items: tuple[ScoredCandidate, ...] = ()
    preselected_id: int | None = None
    suggested_query: str | None = None
    reasons: frozenset[OcrMatchReason] = field(default_factory=frozenset)

    @property
    def top_score(self) -> float | None:
        return self.items[0].score if self.items else None


_WORD = re.compile(r"[0-9a-z]+")


def _trigrams(value: str) -> set[str]:
    grams: set[str] = set()
    for word in _WORD.findall(value.lower()):
        padded = f"  {word} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """Same value as pg_trgm `similarity()` for already-normalized ASCII keys."""
    left, right = _trigrams(a), _trigrams(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


_MASS = re.compile(r"([0-9]+(?:\.[0-9]+)?) (mcg|mg|g)")
_TO_MG = {"mcg": Decimal("0.001"), "mg": Decimal(1), "g": Decimal(1000)}


def _comparable(part: str) -> str:
    """Convert mass units to mg (QD-38: never across dimensions); keep other units verbatim."""
    match = _MASS.fullmatch(part)
    if match is None:
        return part
    try:
        mg = Decimal(match[1]) * _TO_MG[match[2]]
    except InvalidOperation:
        return part
    text = format(mg.normalize(), "f")
    return f"{text} mg"


def strength_parts(evidence: StrengthEvidence) -> frozenset[str]:
    """Every component the text states, in comparable form; empty when none was parsed."""
    parts: set[str] = set()
    for value in evidence.values:
        for occurrence in value.occurrences:
            parts.update(_comparable(p) for p in (occurrence.parts or (occurrence.canonical,)))
    return frozenset(parts)
