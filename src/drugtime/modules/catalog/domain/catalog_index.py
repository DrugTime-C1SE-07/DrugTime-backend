"""Immutable OCR evidence and catalog retrieval values; none verifies a medicine."""

from dataclasses import dataclass
from enum import StrEnum

from drugtime.modules.catalog.domain.medication import CatalogMedication


class StrengthStatus(StrEnum):
    PARSED = "parsed"
    UNPARSED = "unparsed"


@dataclass(frozen=True, slots=True)
class StrengthOccurrence:
    line_id: int
    source_text: str
    start: int
    end: int
    canonical: str | None
    parts: tuple[str, ...] = ()
    status: StrengthStatus = StrengthStatus.PARSED
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StrengthValue:
    canonical: str
    count: int
    occurrences: tuple[StrengthOccurrence, ...]


@dataclass(frozen=True, slots=True)
class StrengthEvidence:
    values: tuple[StrengthValue, ...] = ()
    unparsed: tuple[StrengthOccurrence, ...] = ()
    has_conflict: bool = False
    has_unparsed: bool = False
    has_ambiguous_line: bool = False


@dataclass(frozen=True, slots=True)
class RemovedSpan:
    start: int
    end: int
    source_text: str
    reason: str


@dataclass(frozen=True, slots=True)
class OcrLine:
    line_id: int
    raw: str
    raw_start: int
    raw_end: int
    line_ending: str
    clean: str
    key: str
    name_key: str
    strengths: tuple[StrengthOccurrence, ...]
    unparsed_strengths: tuple[StrengthOccurrence, ...]
    removed_spans: tuple[RemovedSpan, ...]
    query_eligible: bool
    eligibility_reason: str


@dataclass(frozen=True, slots=True)
class OcrCluster:
    cluster_id: int
    member_line_ids: tuple[int, ...]
    count: int
    representative_line_id: int
    name_key: str
    query_eligible: bool
    strength_evidence: StrengthEvidence


@dataclass(frozen=True, slots=True)
class NormalizedOcrText:
    raw_text: str
    lines: tuple[OcrLine, ...] = ()
    clusters: tuple[OcrCluster, ...] = ()
    strength_evidence: StrengthEvidence = StrengthEvidence()


class MatchKind(StrEnum):
    NAME = "name"
    RAW_ACTIVE_INGREDIENT = "raw_active_ingredient"
    INGREDIENT_ALIAS = "ingredient_alias"


@dataclass(frozen=True, slots=True)
class CatalogHit:
    medication: CatalogMedication
    alias_id: int | None = None
    alias_text: str | None = None
    active_ingredient_id: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogQueryResult:
    hits: tuple[CatalogHit, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class MatchSource:
    query_key: str
    cluster_id: int
    line_ids: tuple[int, ...]
    kind: MatchKind
    alias_id: int | None = None
    alias_text: str | None = None
    active_ingredient_id: int | None = None


@dataclass(frozen=True, slots=True)
class OcrCatalogCandidate:
    medication: CatalogMedication
    sources: tuple[MatchSource, ...]


@dataclass(frozen=True, slots=True)
class QueryCoverage:
    cluster_id: int
    query_key: str
    kind: MatchKind
    truncated: bool


@dataclass(frozen=True, slots=True)
class OcrCatalogCluster:
    cluster_id: int
    candidates: tuple[OcrCatalogCandidate, ...]


@dataclass(frozen=True, slots=True)
class OcrCatalogLookup:
    normalized: NormalizedOcrText
    clusters: tuple[OcrCatalogCluster, ...] = ()
    coverage: tuple[QueryCoverage, ...] = ()


def summarize_strengths(lines: tuple[OcrLine, ...]) -> StrengthEvidence:
    """One vote per canonical per source line, while retaining every occurrence."""
    buckets: dict[str, list[StrengthOccurrence]] = {}
    unknown = []
    ambiguous = False
    for line in lines:
        distinct = set()
        unknown.extend(line.unparsed_strengths)
        for occurrence in line.strengths:
            buckets.setdefault(occurrence.canonical, []).append(occurrence)
            distinct.add(occurrence.canonical)
        ambiguous |= len(distinct) > 1
    values = tuple(
        sorted(
            (
                StrengthValue(key, len({o.line_id for o in occurrences}), tuple(occurrences))
                for key, occurrences in buckets.items()
            ),
            key=lambda value: (-value.count, value.canonical),
        )
    )
    return StrengthEvidence(values, tuple(unknown), len(values) > 1, bool(unknown), ambiguous)
