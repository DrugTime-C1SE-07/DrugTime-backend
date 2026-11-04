"""Score catalog candidates of one OCR scan and decide how confident the suggestion is.

Pure and deterministic: same lookup + same policy → same outcome. Rules: 01-requirement
B3 (strength), B4 (weights), B7 (decision order), B1 (tie group); 03-plan §1.
"""

from dataclasses import dataclass, field

from drugtime.modules.catalog.application.normalize_ocr import normalize_key, normalize_ocr_text
from drugtime.modules.catalog.domain.catalog_index import MatchKind, OcrCatalogLookup
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.domain.ocr_match import (
    FuzzyLookup,
    MatchPolicy,
    OcrMatchOutcome,
    OcrMatchReason,
    OcrMatchStatus,
    ScoredCandidate,
    strength_parts,
    trigram_similarity,
)

_SUGGESTED_QUERY_MAX = 100
_EPS = 1e-9


def catalog_name_key(name: str) -> str:
    """Name key comparable with OCR keys: accents, strengths and dosage forms removed (4.12)."""
    normalized = normalize_ocr_text(name)
    key = normalized.lines[0].name_key if normalized.lines else ""
    return key or normalize_key(name)


def catalog_strength(strength_text: str | None) -> frozenset[str] | None:
    """Comparable parts of the catalog strength; None when absent or not fully parsed (B3-7)."""
    if not strength_text or not strength_text.strip():
        return None
    evidence = normalize_ocr_text(strength_text).strength_evidence
    if evidence.has_unparsed or not evidence.values:
        return None
    return strength_parts(evidence)


@dataclass
class _Entry:
    medication: CatalogMedication
    name_key: str
    strength: frozenset[str] | None
    name: float = 0.0
    ingredient: bool = False
    line_ids: set[int] = field(default_factory=set)
    name_keys: set[str] = field(default_factory=set)  # OCR keys that reached it by name
    strength_score: float = 0.0
    conflict: bool = False
    unverified: bool = False
    score: float = 0.0

    @property
    def identity(self) -> tuple:
        form = normalize_key(self.medication.dosage_form or "")
        return (self.name_key, self.strength, form)


def _collect(lookup: OcrCatalogLookup, fuzzy: FuzzyLookup) -> dict[int, _Entry]:
    entries: dict[int, _Entry] = {}

    def entry(med: CatalogMedication) -> _Entry:
        if med.id not in entries:
            entries[med.id] = _Entry(
                med, catalog_name_key(med.name), catalog_strength(med.strength_text)
            )
        return entries[med.id]

    # All clusters feed one list: a scan is about one medicine (A5, AC20).
    for cluster in lookup.clusters:
        for candidate in cluster.candidates:
            e = entry(candidate.medication)
            for source in candidate.sources:
                e.line_ids.update(source.line_ids)
                if source.kind == MatchKind.NAME:
                    e.name = max(e.name, trigram_similarity(source.query_key, e.name_key))
                    e.name_keys.add(source.query_key)
                else:
                    e.ingredient = True
    for hit in fuzzy.hits:
        e = entry(hit.medication)
        e.line_ids.update(hit.line_ids)
        e.name_keys.add(hit.query_key)
        e.name = max(e.name, trigram_similarity(hit.query_key, e.name_key))
    return entries


def _brand_line_conflict(
    lookup: OcrCatalogLookup, ranked: list[_Entry], top: _Entry, policy: MatchPolicy
) -> bool:
    """R2 (03-plan §1): an OCR name line that matches no active ingredient or alias of any
    catalog medicine, and is not similar to any candidate's ingredient text, is a brand
    line; `top` must be among the medicines most similar to it."""
    ingredient_keys = {
        source.query_key
        for cluster in lookup.clusters
        for candidate in cluster.candidates
        for source in candidate.sources
        if source.kind != MatchKind.NAME
    }
    ingredient_texts = {
        normalize_key(e.medication.active_ingredient)
        for e in ranked
        if e.medication.active_ingredient
    }
    for key in sorted({c.query_key for c in lookup.coverage} - ingredient_keys):
        # 4.12 keeps a combination line as one key ("paracetamol caffeine"): compare it
        # with the whole ingredient text instead of requiring a substring hit.
        if any(
            trigram_similarity(key, text) >= policy.ingredient_line_similarity
            for text in ingredient_texts
        ):
            continue
        similarity = {
            id(e): trigram_similarity(key, e.name_key) for e in ranked if key in e.name_keys
        }
        if id(top) not in similarity or similarity[id(top)] < max(similarity.values()) - _EPS:
            return True
    return False


def _best_name_has_several_strengths(ranked: list[_Entry]) -> bool:
    """R1 reason: the best-named group has ≥ 2 catalog strengths (OCR read none)."""
    best = max(e.name for e in ranked)
    keys = {e.name_key for e in ranked if e.name >= best - _EPS}
    return any(
        len({e.strength for e in ranked if e.name_key == key and e.strength is not None}) > 1
        for key in keys
    )


def _suggested_query(lookup: OcrCatalogLookup) -> str | None:
    clusters = sorted(
        (c for c in lookup.normalized.clusters if c.query_eligible and c.name_key.strip()),
        key=lambda c: (-c.count, c.cluster_id),
    )
    if not clusters:
        return None
    return clusters[0].name_key.strip()[:_SUGGESTED_QUERY_MAX].strip() or None


def score_ocr_matches(
    lookup: OcrCatalogLookup, fuzzy: FuzzyLookup, policy: MatchPolicy, limit: int
) -> OcrMatchOutcome:
    if not 1 <= limit <= 10:
        raise ValueError("OCR match limit must be within 1..10")
    normalized = lookup.normalized
    evidence = normalized.strength_evidence
    ocr_parts = strength_parts(evidence)
    eligible = {line.line_id for line in normalized.lines if line.query_eligible}
    entries = _collect(lookup, fuzzy)

    # Strength rules (B3). OCR stated a strength → keep only candidates it explains.
    excluded = False
    if ocr_parts:
        for med_id in list(entries):
            e = entries[med_id]
            if e.strength is None:
                continue  # rule 7: kept, strength unknown, never matched
            if e.strength == ocr_parts:
                e.strength_score = 1.0  # rules 1, 5
            elif e.strength < ocr_parts:
                e.strength_score, e.conflict = 1.0, True  # rule 3
            else:
                del entries[med_id]  # rules 2, 5: never suggest a near-identical medicine
                excluded = True
    else:
        groups: dict[str, set[frozenset[str]]] = {}
        for e in entries.values():
            if e.strength is not None:
                groups.setdefault(e.name_key, set()).add(e.strength)
        for e in entries.values():
            if e.strength is not None and len(groups[e.name_key]) == 1:
                e.strength_score, e.unverified = 1.0, True  # B2: single strength for the name

    for e in entries.values():
        vote = len(e.line_ids & eligible) / len(eligible) if eligible else 0.0
        raw = (
            policy.weight_name * e.name
            + policy.weight_strength * e.strength_score
            + policy.weight_ingredient * (1.0 if e.ingredient else 0.0)
            + policy.weight_vote * min(vote, 1.0)
        )
        # Rounded once, before ranking, so the published order equals the decision order.
        e.score = round(min(max(raw, 0.0), 1.0), 3)

    ranked = sorted(entries.values(), key=lambda e: (-e.score, e.medication.id))
    suggested = _suggested_query(lookup)
    reasons: set[OcrMatchReason] = set()

    if not ranked:
        if excluded:
            reasons.add(OcrMatchReason.STRENGTH_MISMATCH)
        return OcrMatchOutcome(OcrMatchStatus.NO_MATCH, (), None, suggested, frozenset(reasons))
    top = ranked[0]
    if top.score < policy.low_threshold:
        reasons.add(OcrMatchReason.BELOW_THRESHOLD)
        return OcrMatchOutcome(OcrMatchStatus.NO_MATCH, (), None, suggested, frozenset(reasons))

    blocked = False
    if top.strength is None:
        blocked = True  # B3-7; the contract has no dedicated code (03-plan Q2)
    if evidence.has_unparsed:
        blocked = True
        reasons.add(OcrMatchReason.STRENGTH_UNPARSED)
    if not ocr_parts and top.strength is not None and not top.unverified:
        blocked = True
        reasons.add(OcrMatchReason.MULTIPLE_STRENGTHS)
    if top.conflict:
        blocked = True
        reasons.add(OcrMatchReason.STRENGTH_CONFLICT)
    if fuzzy.truncated or any(c.truncated for c in lookup.coverage):
        blocked = True
        reasons.add(OcrMatchReason.TRUNCATED)
    if top.name < max(e.name for e in ranked) - _EPS:
        blocked = True  # R1: another candidate matches the read name better
        if not ocr_parts and _best_name_has_several_strengths(ranked):
            reasons.add(OcrMatchReason.MULTIPLE_STRENGTHS)
    if _brand_line_conflict(lookup, ranked, top, policy):
        blocked = True  # R2; no dedicated reason code (03-plan Q2)
    runner_up = next((e for e in ranked[1:] if e.identity != top.identity), None)
    if runner_up is not None and top.score - runner_up.score < policy.margin:
        blocked = True
        if runner_up.name_key != top.name_key:
            reasons.add(OcrMatchReason.LASA_CLOSE)
    if sum(1 for e in ranked if e.identity == top.identity and e.score == top.score) > 1:
        reasons.add(OcrMatchReason.TIE)  # B1: same name, strength, form; may still match

    items = tuple(ScoredCandidate(e.medication, e.score) for e in ranked[:limit])
    if not blocked and top.score >= policy.threshold:
        if top.unverified:
            reasons.add(OcrMatchReason.STRENGTH_UNVERIFIED)
        return OcrMatchOutcome(
            OcrMatchStatus.MATCHED, items, top.medication.id, None, frozenset(reasons)
        )
    if top.score < policy.threshold:
        reasons.add(OcrMatchReason.BELOW_THRESHOLD)
    return OcrMatchOutcome(
        OcrMatchStatus.LOW_CONFIDENCE, items, None, suggested, frozenset(reasons)
    )
