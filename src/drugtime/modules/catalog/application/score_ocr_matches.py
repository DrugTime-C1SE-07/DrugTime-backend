"""Score catalog candidates of one OCR scan and decide how confident the suggestion is.

Pure and deterministic: same lookup + same policy → same outcome. Rules: 01-requirement
B3 (strength), B4 (weights), B7 (decision order), B1 (tie group); 03-plan §1.
adhoc-20261106 (03-plan §1): brand vs active-ingredient evidence, per-candidate ingredient
score, strength read from the ingredient text, name token coverage, narrower truncation.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

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
_TOKEN = re.compile(r"[0-9a-z]+")
# Components of an ingredient text: "A 500mg; B 10mg" or "A 500 mg, B 5 mg". A comma
# without a following space stays ("1,2mg", "2,4-dichlorobenzyl").
_INGREDIENT_SEPARATOR = re.compile(r";|,(?=\s)")
# C6: "(dưới dạng Atorvastatin calci 10,36mg)" states the salt, not the strength.
_SALT_NOTE = re.compile(r"\([^()]*?(?:duoi dang|tuong duong)[^()]*\)")
# C3: name evidence a brand line needs before ingredient lines lose their name credit.
# Chosen on the pilot-002 raw set; to be calibrated in 4.17.
_BRAND_SIMILARITY = 0.5


def _components(text: str) -> str:
    """One strength component per line, without salt-equivalence notes."""
    return _INGREDIENT_SEPARATOR.sub("\n", _SALT_NOTE.sub(" ", normalize_key(text)))


def catalog_name_key(name: str) -> str:
    """Name key comparable with OCR keys: accents, strengths and dosage forms removed (4.12)."""
    normalized = normalize_ocr_text(name)
    key = normalized.lines[0].name_key if normalized.lines else ""
    return key or normalize_key(name)


@lru_cache(maxsize=8192)
def _parsed_strength(text: str) -> frozenset[str] | None:
    evidence = normalize_ocr_text(text).strength_evidence
    if evidence.has_unparsed or not evidence.values:
        return None
    return strength_parts(evidence)


def catalog_strength(
    strength_text: str | None, active_ingredient: str | None = None
) -> tuple[frozenset[str] | None, bool]:
    """(comparable strength parts, derived) per 03-plan §1.3. Directly readable
    `strength_text` is authoritative; text readable only once split into components or
    without a salt note, or the ingredient text when `strength_text` is empty, is derived.
    None when absent or not fully parsed (B3-7)."""
    if strength_text and strength_text.strip():
        direct = _parsed_strength(strength_text)
        if direct is not None and not _SALT_NOTE.search(normalize_key(strength_text)):
            return direct, False
        parts = _parsed_strength(_components(strength_text))
        if parts is not None:
            return parts, True
        return direct, False
    if active_ingredient and active_ingredient.strip():
        parts = _parsed_strength(_components(active_ingredient))
        if parts is not None:
            return parts, True
    return None, False


# C2: packaging and dosage-form words never distinguish one medicine from another.
_GENERIC_WORDS = frozenset({
    "tablet", "tablets", "tab", "tabs", "film", "coated", "capsule", "capsules", "caps",
    "lozenge", "lozenges", "vien", "nen", "nang", "bao", "phim", "hop", "vi", "sui", "siro",
    "mem", "cung", "goi", "ong", "chai", "lo",
})


def _tokens(text: str) -> list[str]:
    """Distinctive words: no bare numbers, no packaging words (03-plan §1.2)."""
    return [
        t
        for t in _TOKEN.findall(text)
        if len(t) >= 2 and not t.isdigit() and t not in _GENERIC_WORDS
    ]


def _coverage(name_key: str, ocr_tokens: set[str]) -> float:
    """Share of the catalog name's words read anywhere on the scan (names split over lines)."""
    words = _tokens(name_key)
    return sum(1 for w in words if w in ocr_tokens) / len(words) if words else 0.0


@dataclass
class _Entry:
    medication: CatalogMedication
    name_key: str
    strength: frozenset[str] | None
    derived: bool = False  # strength read from the ingredient text, not strength_text
    name_by_key: dict[str, float] = field(default_factory=dict)
    retrieved_ingredient: bool = False  # reached by an ingredient/alias lookup
    ingredient: bool = False
    line_ids: set[int] = field(default_factory=set)
    name_keys: set[str] = field(default_factory=set)  # OCR keys that reached it by name
    name: float = 0.0
    lost_name: bool = False  # name evidence removed by the brand-line rule (Q2)
    strength_score: float = 0.0
    conflict: bool = False
    unverified: bool = False
    score: float = 0.0

    @property
    def identity(self) -> tuple:
        form = normalize_key(self.medication.dosage_form or "")
        return (self.name_key, self.strength, form)

    def add_name(self, key: str) -> None:
        self.name_keys.add(key)
        if not _tokens(key):
            return  # C2b: only numbers or packaging words, no name evidence
        similarity = trigram_similarity(key, self.name_key)
        self.name_by_key[key] = max(self.name_by_key.get(key, 0.0), similarity)


def _collect(lookup: OcrCatalogLookup, fuzzy: FuzzyLookup) -> dict[int, _Entry]:
    entries: dict[int, _Entry] = {}

    def entry(med: CatalogMedication) -> _Entry:
        if med.id not in entries:
            strength, derived = catalog_strength(med.strength_text, med.active_ingredient)
            entries[med.id] = _Entry(med, catalog_name_key(med.name), strength, derived)
        return entries[med.id]

    # All clusters feed one list: a scan is about one medicine (A5, AC20).
    for cluster in lookup.clusters:
        for candidate in cluster.candidates:
            e = entry(candidate.medication)
            for source in candidate.sources:
                e.line_ids.update(source.line_ids)
                if source.kind == MatchKind.NAME:
                    e.add_name(source.query_key)
                else:
                    e.retrieved_ingredient = True
    for hit in fuzzy.hits:
        e = entry(hit.medication)
        e.line_ids.update(hit.line_ids)
        e.add_name(hit.query_key)
    return entries


def _ingredient_keys(
    lookup: OcrCatalogLookup, entries: list[_Entry], policy: MatchPolicy
) -> set[str]:
    """OCR keys read as an active ingredient: an ingredient/alias lookup hit, or similar to a
    candidate's ingredient text (4.12 keeps a combination line as one key)."""
    retrieved = {
        source.query_key
        for cluster in lookup.clusters
        for candidate in cluster.candidates
        for source in candidate.sources
        if source.kind != MatchKind.NAME
    }
    texts = {
        normalize_key(e.medication.active_ingredient)
        for e in entries
        if e.medication.active_ingredient
    }
    similar = {
        key
        for key in {c.query_key for c in lookup.coverage} - retrieved
        if any(trigram_similarity(key, t) >= policy.ingredient_line_similarity for t in texts)
    }
    return retrieved | similar


def _brand_line_conflict(
    lookup: OcrCatalogLookup, ranked: list[_Entry], top: _Entry, ingredient_keys: set[str]
) -> bool:
    """R2 (4.13 03-plan §1): an OCR name line that is not an ingredient line is a brand
    line; `top` must be among the medicines most similar to it."""
    for key in sorted({c.query_key for c in lookup.coverage} - ingredient_keys):
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


def _apply_strength_rules(
    entries: dict[int, _Entry], ocr_parts: frozenset[str]
) -> bool:
    """B3 rules; returns whether a candidate was excluded (rules 2, 5)."""
    excluded = False
    if ocr_parts:
        for med_id in list(entries):
            e = entries[med_id]
            if e.strength is None:
                continue  # rule 7: kept, strength unknown, never matched
            if e.strength == ocr_parts:
                e.strength_score = 1.0  # rules 1, 5
            elif e.strength < ocr_parts:
                # rule 3: explains only part of what the box states → share of it (NN3)
                e.strength_score = len(e.strength) / len(ocr_parts)
                e.conflict = True
            elif e.derived:
                e.strength = None  # a derived strength never excludes; unknown instead
            else:
                del entries[med_id]  # rules 2, 5: never suggest a near-identical medicine
                excluded = True
    else:
        groups: dict[str, set[frozenset[str]]] = {}
        for e in entries.values():
            if e.strength is not None:  # C1: derived counts too; it never preselects
                groups.setdefault(e.name_key, set()).add(e.strength)
        for e in entries.values():
            if e.strength is not None and len(groups[e.name_key]) == 1:
                e.strength_score, e.unverified = 1.0, True  # B2: single strength for the name
    return excluded


def _ingredient_named(e: _Entry, ingredient_keys: set[str]) -> bool:
    """C5: a name word (≥ 4 letters) found in the medicine's own ingredient text, e.g.
    "Paracetamol 500mg"; never "Atoris". Without ingredient text: the name holds an
    OCR ingredient key."""
    text = normalize_key(e.medication.active_ingredient or "")
    if text:
        return any(len(t) >= 4 and t in text for t in _tokens(e.name_key))
    return any(key in e.name_key for key in ingredient_keys)


def _apply_evidence(
    lookup: OcrCatalogLookup,
    entries: list[_Entry],
    ingredient_keys: set[str],
    ocr_parts: frozenset[str],
    policy: MatchPolicy,
) -> bool:
    """Ingredient and name evidence of every candidate; returns whether the brand-line rule
    removed name evidence from some candidate (Q2)."""
    eligible_lines = [line for line in lookup.normalized.lines if line.query_eligible]
    key_lines: dict[str, set[int]] = {}
    for line in eligible_lines:
        key_lines.setdefault(line.name_key, set()).add(line.line_id)
    all_tokens = {t for line in eligible_lines for t in _tokens(line.name_key)}
    brand_tokens = {
        t
        for line in eligible_lines
        if line.name_key not in ingredient_keys
        for t in _tokens(line.name_key)
    }

    # NN2: judged on the candidate's own ingredient text, not on which ids a lookup kept.
    for e in entries:
        text = normalize_key(e.medication.active_ingredient or "")
        explained = {
            key
            for key in ingredient_keys
            if text
            and (key in text or trigram_similarity(key, text) >= policy.ingredient_line_similarity)
        }
        e.ingredient = e.retrieved_ingredient or bool(explained)
        for key in explained:
            e.line_ids.update(key_lines.get(key, ()))

    def brand_name(e: _Entry) -> float:
        sims = [s for k, s in e.name_by_key.items() if k not in ingredient_keys]
        return max([*sims, _coverage(e.name_key, brand_tokens)])

    def any_name(e: _Entry) -> float:
        return max([*e.name_by_key.values(), _coverage(e.name_key, all_tokens)])

    def strong_brand(e: _Entry) -> bool:  # C3
        sims = [s for k, s in e.name_by_key.items() if k not in ingredient_keys]
        return (
            max(sims, default=0.0) >= _BRAND_SIMILARITY
            or _coverage(e.name_key, brand_tokens) >= 1.0 - _EPS
        )

    # Q2: a brand line that matches a catalog medicine of the same ingredient makes the
    # ingredient lines evidence only, never name evidence (01 §3.0).
    brand = {id(e): brand_name(e) for e in entries}
    brand_present = any(
        not _ingredient_named(e, ingredient_keys) and e.ingredient and strong_brand(e)
        for e in entries
    )
    # Rule N (03-plan §1.2): when a candidate explains every strength of a combination box,
    # a candidate explaining only part of it gets no name evidence from ingredient lines.
    full_combination = len(ocr_parts) >= 2 and any(e.strength == ocr_parts for e in entries)
    removed = False
    for e in entries:
        named = any_name(e)
        if brand_present:
            e.name = brand[id(e)]
            e.lost_name = named > e.name + _EPS
            removed |= e.lost_name
        elif full_combination and e.strength is not None and e.strength < ocr_parts:
            e.name = brand[id(e)]
        else:
            e.name = named
    return removed


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
    excluded = _apply_strength_rules(entries, ocr_parts)
    remaining = list(entries.values())
    ingredient_keys = _ingredient_keys(lookup, remaining, policy)
    name_removed = _apply_evidence(lookup, remaining, ingredient_keys, ocr_parts, policy)

    for e in remaining:
        vote = len(e.line_ids & eligible) / len(eligible) if eligible else 0.0
        raw = (
            policy.weight_name * e.name
            + policy.weight_strength * e.strength_score
            + policy.weight_ingredient * (1.0 if e.ingredient else 0.0)
            + policy.weight_vote * min(vote, 1.0)
        )
        # Rounded once, before ranking, so the published order equals the decision order.
        e.score = round(min(max(raw, 0.0), 1.0), 3)

    ranked = sorted(remaining, key=lambda e: (-e.score, e.medication.id))
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
    if top.strength is None or top.derived:
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
    # NN5: a cut name lookup that brought the top candidate can hide its competitors.
    # C4: so can a cut ingredient lookup when the top is ingredient-named: a brand of the
    # same ingredient, whose line was unreadable, may be the medicine on the box (QD-39).
    top_ingredient_named = _ingredient_named(top, ingredient_keys)
    if fuzzy.truncated or any(
        c.truncated
        and (
            (c.kind == MatchKind.NAME and c.query_key in top.name_keys)
            or (c.kind != MatchKind.NAME and top_ingredient_named)
        )
        for c in lookup.coverage
    ):
        blocked = True
        reasons.add(OcrMatchReason.TRUNCATED)
    if top.name < max(e.name for e in ranked) - _EPS:
        blocked = True  # R1: another candidate matches the read name better
        if not ocr_parts and _best_name_has_several_strengths(ranked):
            reasons.add(OcrMatchReason.MULTIPLE_STRENGTHS)
    if _brand_line_conflict(lookup, ranked, top, ingredient_keys):
        blocked = True  # R2; no dedicated reason code (03-plan Q2)
    if name_removed and top.name < 1.0 - _EPS:
        blocked = True  # Q2 ranked on a brand line read only approximately; no reason code
    runner_up = next((e for e in ranked[1:] if e.identity != top.identity), None)
    if runner_up is not None and top.score - runner_up.score < policy.margin:
        blocked = True
        if runner_up.name_key != top.name_key:
            reasons.add(OcrMatchReason.LASA_CLOSE)
    if sum(1 for e in ranked if e.identity == top.identity and e.score == top.score) > 1:
        reasons.add(OcrMatchReason.TIE)  # B1: same name, strength, form; may still match

    # YT1: a weak candidate below T_low is never listed, even under a good first one.
    shown = [e for e in ranked if e.score >= policy.low_threshold][:limit]
    items = tuple(ScoredCandidate(e.medication, e.score) for e in shown)
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
