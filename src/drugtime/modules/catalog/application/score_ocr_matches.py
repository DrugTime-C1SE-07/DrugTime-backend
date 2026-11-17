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
# adhoc-20261116 B1 (03-plan §1.1): word-level similarity for a misread word of a name, the
# weaker one when the top is ingredient-named, and the length of a word that may be an
# unreadable brand. Chosen on the pilot-002 raw set and the 4.13 bench (04 §5).
_TOKEN_SIMILARITY = 0.6
_GENERIC_TOKEN_SIMILARITY = 0.4
_INGREDIENT_TOKEN_SIMILARITY = 0.5  # long ingredient words misread ("chionpheniramine")
_BRAND_WORD_MIN = 5
# Words of company, pharmacy, prescription, standard and packaging lines: never the name of
# a medicine, so they are no evidence of another medicine (01 NN3). Generic words, not
# names of companies or products.
_NOISE_WORDS = frozenset({
    "cty", "cong", "ty", "tnhh", "jsc", "ltd", "co", "corp", "phan", "duoc", "pham",
    "pharma", "pharm", "pharmaceutical", "pharmaceuticals", "international", "nha", "thuoc",
    "hotline", "chinh", "hang", "gmp", "who", "rx", "ke", "don", "ban", "theo", "box", "of",
    "blister", "blisters", "each", "contains", "indication", "indications", "made", "in",
    "viet", "nam", "vietnam", "san", "xuat", "boi", "dia", "chi", "tinh", "huyen", "quan",
    "duong", "so", "lo", "hsd", "nsx", "exp", "mfg", "batch", "lot", "reg", "no", "sdk",
    "effervescent", "effervescents", "manufactured", "marketed", "distributed", "prescription",
    "composition", "directed", "physician", "dosage", "warning", "store", "protect",
    "www", "com", "vn", "net",
})
# Misreads of the longer noise words ("manutechro", "effervescen") are noise too.
_LONG_NOISE_WORDS = tuple(w for w in _NOISE_WORDS if len(w) >= 6)
_NOISE_SIMILARITY = 0.5


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
        """Same medicine: same name words (adhoc-20261116 B2: "Atorvastatin 10" and
        "Atorvastatin 10mg" are registrations of one medicine), strength and dosage form."""
        form = normalize_key(self.medication.dosage_form or "")
        return (self.name_words, self.strength, form)

    @property
    def name_words(self) -> tuple[str, ...]:
        return tuple(_name_tokens(self.name_key))

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


def _is_noise(word: str) -> bool:
    return word in _NOISE_WORDS or (
        len(word) >= 6
        and any(trigram_similarity(word, w) >= _NOISE_SIMILARITY for w in _LONG_NOISE_WORDS)
    )


def _name_tokens(text: str) -> list[str]:
    """Words that can name a medicine: `_tokens` without company, pharmacy, prescription and
    packaging words (adhoc-20261116 01 NN3). Used by R2 and `suggested_query` only."""
    return [t for t in _tokens(text) if not _is_noise(t)]


def _token_close(word: str, words: list[str], threshold: float = _TOKEN_SIMILARITY) -> bool:
    return any(trigram_similarity(word, w) >= threshold for w in words)


def _fragment_of(tokens: list[str], text: str, threshold: float = _TOKEN_SIMILARITY) -> bool:
    """Every word read is (a misread of) a word of `text`: "decolgeni", "forte" of
    "Decolgen Forte"; "alorvastatin" of the top's ingredient "Atorvastatin"."""
    words = _tokens(text)
    return bool(tokens) and all(_token_close(t, words, threshold) for t in tokens)


def _brand_line_conflict(
    lookup: OcrCatalogLookup, ranked: list[_Entry], top: _Entry, ingredient_keys: set[str]
) -> bool:
    """R2 (4.13 03-plan §1), narrowed by adhoc-20261116 B1 (03-plan §1.1, 04 §5): a line that
    is not an ingredient line blocks only when it reads, by its name words (no numbers, no
    company or packaging words), as another medicine better than as the top, shares a word
    with it, and is no fragment of the top's name or ingredient. When the top is
    ingredient-named (a generic box), weaker evidence blocks, and so does a short unreadable
    brand-like line: the brand of the same ingredient may be the medicine (C4, QD-39)."""
    ingredient_text = normalize_key(top.medication.active_ingredient or "")
    ingredient_words = _tokens(ingredient_text)
    generic_top = _ingredient_named(top, ingredient_keys) or any(
        len(t) >= 4 and _token_close(t, ingredient_words) for t in _tokens(top.name_key)
    )  # also "Finasteride" whose catalog ingredient is spelled "Finasterid"
    top_words = " ".join(_name_tokens(top.name_key))

    def brand_like_unreadable(key: str) -> bool:
        tokens = _name_tokens(key)
        return (
            generic_top
            and bool(tokens)
            and not any(_is_noise(t) for t in _tokens(key))
            and len(tokens) <= 2
            # letters, not length: "apo1ets" is a misread brand (bench 4.13 C4)
            and any(sum(c.isalpha() for c in t) >= _BRAND_WORD_MIN for t in tokens)
            and not _fragment_of(tokens, top.name_key)
            and not (ingredient_text and _fragment_of(
                tokens, ingredient_text, _INGREDIENT_TOKEN_SIMILARITY))
        )

    # A line too garbled to be looked up ("APO1ETS") may still be the brand on a generic box.
    if any(
        brand_like_unreadable(line.name_key)
        for line in lookup.normalized.lines
        if not line.query_eligible
    ):
        return True
    for key in sorted({c.query_key for c in lookup.coverage} - ingredient_keys):
        tokens = _name_tokens(key)
        if not tokens or _fragment_of(tokens, top.name_key):
            continue
        if ingredient_text and _fragment_of(tokens, ingredient_text, _INGREDIENT_TOKEN_SIMILARITY):
            continue  # a misread ingredient line of the top itself
        candidates = [e for e in ranked if key in e.name_keys]
        if not candidates:
            # Names nothing in the catalog: only a short brand-like line on a generic box.
            if brand_like_unreadable(key):
                return True
            continue
        words = " ".join(tokens)
        similarity = {
            id(e): (trigram_similarity(words, " ".join(_name_tokens(e.name_key))), e)
            for e in candidates
        }
        best, other = max(similarity.values(), key=lambda pair: (pair[0], -pair[1].medication.id))
        top_similarity = trigram_similarity(words, top_words) if top_words else 0.0
        if other is top or best <= top_similarity + _EPS:
            continue
        # A generic top accepts weaker word evidence of a brand ("konlcmax" ~ "konlemax").
        threshold = _GENERIC_TOKEN_SIMILARITY if generic_top else _TOKEN_SIMILARITY
        other_words = _name_tokens(other.name_key)
        shares_word = any(
            len(t) >= 4 and _token_close(t, other_words, threshold) for t in tokens
        )
        if not shares_word:
            continue  # e.g. "nha thuoc ngoc anh" vs "Thuốc cảm lạnh an nhân"
        if generic_top or best >= _BRAND_SIMILARITY:
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


def _suggested_query(
    lookup: OcrCatalogLookup, fuzzy: FuzzyLookup, ranked: list[_Entry], policy: MatchPolicy
) -> str | None:
    """adhoc-20261116 B6: the medicine name read most reliably, for the manual search.
    (1) the top candidate's name; (2) the most repeated line whose name found catalog
    medicines; (3) the most repeated line that can name a medicine (no company, pharmacy,
    prescription or packaging word); otherwise None."""

    def cut(key: str) -> str | None:
        return key.strip()[:_SUGGESTED_QUERY_MAX].strip() or None

    if ranked and ranked[0].score >= policy.low_threshold:
        return cut(catalog_name_key(ranked[0].medication.name))
    named = {
        source.cluster_id
        for cluster in lookup.clusters
        for candidate in cluster.candidates
        for source in candidate.sources
        if source.kind == MatchKind.NAME
    } | {hit.cluster_id for hit in fuzzy.hits}
    clusters = sorted(
        (
            c
            for c in lookup.normalized.clusters
            if c.query_eligible and _name_tokens(c.name_key)
        ),
        key=lambda c: (c.cluster_id not in named, -c.count, c.cluster_id),
    )
    for c in clusters:
        if c.cluster_id in named or not any(_is_noise(t) for t in _tokens(c.name_key)):
            return cut(c.name_key)
    return None


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
    suggested = _suggested_query(lookup, fuzzy, ranked, policy)
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
    # B3-7. adhoc-20261116 B4: a strength read from the ingredient text (derived) may match
    # once the box states every one of its strengths and nothing else.
    derived_verified = (
        top.derived and bool(ocr_parts) and top.strength == ocr_parts and not top.conflict
    )
    if top.strength is None or (top.derived and not derived_verified):
        blocked = True  # the contract has no dedicated code (03-plan Q2)
    # adhoc-20261116 B5: an unreadable strength blocks only on a line about the top (its name
    # or ingredient line) or on a line that names nothing (a strength printed on its own);
    # a number misread on a company or packaging line says nothing about the medicine.
    if any(
        line.unparsed_strengths
        and (line.line_id in top.line_ids or not line.query_eligible)
        for line in normalized.lines
    ):
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
    # adhoc-20261116 B3: a cut fuzzy lookup of a key that did not bring the top hides no
    # competitor of it (same narrowing as NN5 for exact lookups).
    if fuzzy.truncated_keys & top.name_keys or any(
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
    # B2: once the box's strength verified the top, a registration of the same name whose
    # strength or form the catalog leaves empty is no different medicine.
    verified = bool(ocr_parts) and top.strength_score >= 1.0 - _EPS and not top.unverified

    def same_medicine(e: _Entry) -> bool:
        if e.identity == top.identity:
            return True
        return (
            verified
            and e.name_words == top.name_words
            and (e.strength is None or not e.medication.dosage_form)
            and e.strength in (None, top.strength)
        )

    runner_up = next((e for e in ranked[1:] if not same_medicine(e)), None)
    if runner_up is not None and top.score - runner_up.score < policy.margin:
        blocked = True
        if runner_up.name_words != top.name_words:
            reasons.add(OcrMatchReason.LASA_CLOSE)
    if top.unverified and any(
        e.name_words == top.name_words and e.strength is None for e in ranked[1:]
    ):
        blocked = True  # T6: an unread strength may be the catalog row without one (QD-39)
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
