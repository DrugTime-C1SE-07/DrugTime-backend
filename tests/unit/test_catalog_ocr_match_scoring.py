"""Scoring, strength rules and status decision of OCR matching (4.13), on synthetic OCR text.

The fake reader mirrors the SQL adapters: substring match on the accent-folded key for the
three 4.12 kinds, and pg_trgm-equivalent similarity for the fuzzy fallback. Real OCR
samples (4.14) can be plugged into `run()` unchanged.
"""

from dataclasses import replace

import pytest

from drugtime.modules.catalog.application.match_ocr_text import match_ocr_text
from drugtime.modules.catalog.application.normalize_ocr import normalize_key, normalize_ocr_text
from drugtime.modules.catalog.application.score_ocr_matches import score_ocr_matches
from drugtime.modules.catalog.domain.catalog_index import (
    CatalogHit,
    CatalogQueryResult,
    MatchKind,
    MatchSource,
    OcrCatalogCandidate,
    OcrCatalogCluster,
    OcrCatalogLookup,
    QueryCoverage,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.domain.ocr_match import (
    FuzzyLookup,
    MatchPolicy,
    trigram_similarity,
)
from drugtime.modules.catalog.domain.ocr_match import (
    OcrMatchReason as R,
)
from drugtime.modules.catalog.domain.ocr_match import (
    OcrMatchStatus as S,
)

POLICY = MatchPolicy()


def med(id_, name, strength="500 mg", ingredient=None, form="Viên nén", has_ingredients=True):
    return CatalogMedication(id_, name, strength, form, has_ingredients, ingredient)


class FakeReader:
    def __init__(self, catalog, *, aliases=None, truncate_kinds=(), fuzzy_truncated=False):
        self.catalog = catalog
        self.aliases = aliases or {}  # alias text -> medication ids
        self.truncate_kinds = set(truncate_kinds)
        self.fuzzy_truncated = fuzzy_truncated
        self.fuzzy_calls = []

    def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
        if kind == MatchKind.NAME:
            hits = [CatalogHit(m) for m in self.catalog if query_key in normalize_key(m.name)]
        elif kind == MatchKind.RAW_ACTIVE_INGREDIENT:
            hits = [
                CatalogHit(m)
                for m in self.catalog
                if m.active_ingredient and query_key in normalize_key(m.active_ingredient)
            ]
        else:
            hits = [
                CatalogHit(m, 1, alias, 1)
                for alias, ids in self.aliases.items()
                if query_key in normalize_key(alias)
                for m in self.catalog
                if m.id in ids
            ]
        return CatalogQueryResult(tuple(hits), kind in self.truncate_kinds)

    def find_fuzzy_name_matches(self, uow, query_key, *, threshold, limit):
        self.fuzzy_calls.append(query_key)
        def sim(m):
            return trigram_similarity(query_key, normalize_key(m.name))

        found = sorted(
            (m for m in self.catalog if sim(m) >= threshold), key=lambda m: (-sim(m), m.id)
        )
        return tuple(found[:limit]), self.fuzzy_truncated or len(found) > limit


def run(text, catalog, *, policy=POLICY, limit=5, **reader_kwargs):
    reader = FakeReader(catalog, **reader_kwargs)
    return match_ocr_text(None, text, limit=limit, policy=policy, reader=reader), reader


def ids(outcome):
    return [c.medication.id for c in outcome.items]


PANADOL_EXTRA = med(10, "Panadol Extra", "500 mg + 65 mg", "Paracetamol, Cafein")
CATALOG = [
    PANADOL_EXTRA,
    med(11, "Panadol", "500 mg", "Paracetamol"),
    med(20, "Hapacol 250", "250 mg", "Paracetamol"),
    med(30, "Efferalgan", "500 mg", "Paracetamol"),
]
ALIASES = {"Paracetamol": {10, 11, 20, 30}, "Caffeine": {10}}


def test_noisy_combination_text_matched__AC1():
    text = "PANAD0L EXTRA\r\nParacetamol 500mg Caffeine 65mg\nPANADOL EXTRA\nHSD 12/2027"
    outcome, _ = run(text, CATALOG, aliases=ALIASES)
    assert outcome.status == S.MATCHED
    assert outcome.preselected_id == 10 == ids(outcome)[0]
    assert outcome.items[0].score >= POLICY.threshold
    assert outcome.suggested_query is None
    assert R.STRENGTH_CONFLICT not in outcome.reasons


def test_combination_values_not_conflict__AC1_AC13():
    outcome, _ = run("Panadol Extra 500mg + 65mg", CATALOG, aliases=ALIASES)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 10
    assert outcome.reasons == frozenset()


@pytest.mark.parametrize("text", ["HSD 12/2027 Lô 123", "", "   ", "12/2027\n123"])
def test_irrelevant_text_never_matched__AC2(text):
    outcome, _ = run(text, CATALOG, aliases=ALIASES)
    assert outcome.status == S.NO_MATCH
    assert outcome.items == () and outcome.preselected_id is None
    assert outcome.suggested_query is None


def test_low_band_low_confidence_with_query__AC3():
    # Partial name, no strength read, single strength in catalog: 0.5 * 0.667 + 0.3 + 0.05.
    catalog = [med(1, "Cefuroxim Kabi", "500 mg")]
    outcome, _ = run("cefuroxim", catalog)
    assert POLICY.low_threshold <= outcome.items[0].score < POLICY.threshold
    assert outcome.status == S.LOW_CONFIDENCE
    assert outcome.preselected_id is None and ids(outcome) == [1]
    assert outcome.reasons == frozenset({R.BELOW_THRESHOLD})
    assert outcome.suggested_query == "cefuroxim"


def test_threshold_from_policy_changes_status__AC10():
    catalog = [med(1, "Cefuroxim Kabi", "500 mg")]
    outcome, _ = run("cefuroxim", catalog, policy=replace(POLICY, threshold=0.6))
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1
    strict = replace(POLICY, low_threshold=0.69, threshold=0.69)
    outcome, _ = run("cefuroxim", catalog, policy=strict)
    assert outcome.status == S.NO_MATCH


def test_below_low_threshold_no_match_only_query__AC3():
    catalog = [med(1, "Cefuroxim Kabi Pharma Extended Release", None)]
    outcome, _ = run("cefuroxim", catalog)
    assert outcome.status == S.NO_MATCH and outcome.items == ()
    assert R.BELOW_THRESHOLD in outcome.reasons
    assert outcome.suggested_query == "cefuroxim"


def test_multiple_strengths_not_preselected__AC4():
    catalog = [med(1, "Amoxicillin", "250 mg"), med(2, "Amoxicillin", "500 mg")]
    outcome, _ = run("AMOXICILLIN\nAmoxicillin", catalog)
    assert outcome.status == S.LOW_CONFIDENCE
    assert outcome.preselected_id is None
    assert ids(outcome) == [1, 2]
    assert R.MULTIPLE_STRENGTHS in outcome.reasons


def test_single_strength_matched_unverified__AC4():
    catalog = [med(1, "Amoxicillin", "500 mg"), med(2, "Augmentin", "625 mg")]
    outcome, _ = run("AMOXICILLIN\nAmoxicillin", catalog)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1
    assert R.STRENGTH_UNVERIFIED in outcome.reasons


def test_order_and_limit_deterministic__AC6():
    catalog = [
        med(i, f"Paracetamol {chr(64 + i)}", "500 mg", "Paracetamol") for i in range(9, 0, -1)
    ]
    first, _ = run("Paracetamol 500mg", catalog, limit=3)
    second, _ = run("Paracetamol 500mg", list(reversed(catalog)), limit=3)
    assert first == second
    assert len(first.items) == 3
    scores = [(-c.score, c.medication.id) for c in first.items]
    assert scores == sorted(scores)
    big, _ = run("Paracetamol 500mg", catalog, limit=10)
    assert len(big.items) == 9
    one, _ = run("Paracetamol 500mg", catalog, limit=1)
    assert len(one.items) == 1


def test_conflicting_strength_not_matched__AC13():
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol"), med(2, "Panadol", "650 mg")]
    outcome, _ = run("PANADOL\nParacetamol 500 mg\nParacetamol 650 mg", catalog)
    assert outcome.status == S.LOW_CONFIDENCE
    assert R.STRENGTH_CONFLICT in outcome.reasons
    assert set(ids(outcome)) == {1, 2}


def test_unparsed_strength_not_matched__AC13():
    catalog = [med(1, "Panadol", "500 mg")]
    outcome, _ = run("PANADOL\n5O0 mg", catalog)  # letter O inside the amount
    assert outcome.status == S.LOW_CONFIDENCE
    assert R.STRENGTH_UNPARSED in outcome.reasons
    assert ids(outcome) == [1]


def test_catalog_strength_unparsable_not_matched():
    catalog = [med(1, "Panadol", "Mỗi viên chứa paracetamol")]
    outcome, _ = run("PANADOL\nPANADOL", catalog)
    assert outcome.status == S.LOW_CONFIDENCE and ids(outcome) == [1]


@pytest.mark.parametrize("kind", list(MatchKind))
def test_truncated_lookup_never_matched__AC14(kind):
    outcome, _ = run("Panadol Extra 500mg + 65mg", CATALOG, aliases=ALIASES, truncate_kinds={kind})
    assert outcome.status == S.LOW_CONFIDENCE
    assert R.TRUNCATED in outcome.reasons


def test_truncated_fuzzy_never_matched__AC14():
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol")]
    outcome, reader = run("PANAD0L 500mg\nParacetamol", catalog, fuzzy_truncated=True)
    assert reader.fuzzy_calls == ["panad0l"]
    assert outcome.status == S.LOW_CONFIDENCE and R.TRUNCATED in outcome.reasons


def test_lasa_close_scores_not_matched__AC15():
    # "doputamin" is a misread equally close to both (similarity 0.5 vs 0.538).
    catalog = [med(1, "Dopamin", "200 mg"), med(2, "Dobutamin", "200 mg")]
    outcome, _ = run("DOPUTAMIN 200mg", catalog)
    assert outcome.status == S.LOW_CONFIDENCE
    assert R.LASA_CLOSE in outcome.reasons
    assert set(ids(outcome)) == {1, 2}


def test_tie_group_matched_whole_group_listed():
    catalog = [med(6230, "Cefuroxim", "500 mg"), med(6101, "Cefuroxim", "500 mg"),
               med(6188, "Cefuroxim", "500 mg")]
    outcome, _ = run("CEFUROXIM 500mg\nCefuroxim", catalog)
    assert outcome.status == S.MATCHED
    assert ids(outcome) == [6101, 6188, 6230] and outcome.preselected_id == 6101
    assert R.TIE in outcome.reasons


def test_same_name_other_form_close_score_low_confidence():
    catalog = [med(1, "Cefuroxim", "500 mg", form="Viên nén"),
               med(2, "Cefuroxim", "500 mg", form="Bột pha tiêm")]
    outcome, _ = run("CEFUROXIM 500mg", catalog)
    assert outcome.status == S.LOW_CONFIDENCE
    assert outcome.preselected_id is None and set(ids(outcome)) == {1, 2}


def test_strength_mismatch_excluded_no_match__AC18():
    catalog = [med(1, "Paracetamol Stada", "250 mg", "Paracetamol")]
    outcome, _ = run("PARACETAMOL STADA\nParacetamol 500 mg", catalog)
    assert outcome.status == S.NO_MATCH and outcome.items == ()
    assert outcome.reasons == frozenset({R.STRENGTH_MISMATCH})
    assert outcome.suggested_query == "paracetamol stada"


def test_partial_combination_excluded__AC18():
    catalog = [med(1, "Panadol Extra", "500 mg + 65 mg")]
    outcome, _ = run("PANADOL EXTRA 500mg", catalog)
    assert outcome.status == S.NO_MATCH and R.STRENGTH_MISMATCH in outcome.reasons


def test_gram_equals_milligram__AC19():
    catalog = [med(1, "Cefuroxim", "500 mg")]
    outcome, _ = run("CEFUROXIM 0,5 g\nCefuroxim", catalog)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1


def test_ml_only_strength_treated_unparsed__AC19():
    catalog = [med(1, "Siro Ho Prospan", "35 mg/5 ml")]
    outcome, _ = run("SIRO HO PROSPAN\n5 ml", catalog)
    assert outcome.status != S.MATCHED
    assert R.STRENGTH_UNPARSED in outcome.reasons


def test_single_result_for_multi_drug_text__AC20():
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol"), med(2, "Amoxicillin", "500 mg")]
    outcome, _ = run("PANADOL 500mg\nPanadol\nAMOXICILLIN", catalog)
    # One status and one ranked list for the whole scan, never one result per cluster.
    assert isinstance(outcome.status, S) and set(ids(outcome)) <= {1, 2}
    assert ids(outcome)[0] == 1  # the medicine read most often ranks first


def test_candidate_without_ingredients_flagged():
    catalog = [med(1, "Thuốc ho Bảo Thanh", "125 ml", has_ingredients=False)]
    outcome, _ = run("THUOC HO BAO THANH", catalog)
    assert ids(outcome) == [1]
    assert outcome.items[0].medication.has_active_ingredients is False


def test_fuzzy_candidate_reaches_score_from_strength_and_ingredient__AC17():
    # Calibration note for 4.17: one misread letter still matches when strength and
    # ingredient agree (0.5 * 0.4545 + 0.3 + 0.15 + 0.05 ≈ 0.727 ≥ T).
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol")]
    outcome, _ = run("PANAD0L 500mg\nParacetamol", catalog)
    assert ids(outcome) == [1]
    assert outcome.items[0].score == pytest.approx(0.727, abs=0.001)


def test_score_rejects_out_of_range_limit():
    lookup = OcrCatalogLookup(normalize_ocr_text("Panadol"))
    with pytest.raises(ValueError):
        score_ocr_matches(lookup, FuzzyLookup(), POLICY, 11)


def test_scores_are_rounded_before_ranking():
    normalized = normalize_ocr_text("abcd efgh")
    lookup = OcrCatalogLookup(
        normalized,
        (
            OcrCatalogCluster(
                1,
                tuple(
                    OcrCatalogCandidate(
                        med(i, "abcd efgh", None),
                        (MatchSource("abcd efgh", 1, (1,), MatchKind.NAME),),
                    )
                    for i in (2, 1)
                ),
            ),
        ),
        (QueryCoverage(1, "abcd efgh", MatchKind.NAME, False),),
    )
    outcome = score_ocr_matches(lookup, FuzzyLookup(), POLICY, 5)
    assert ids(outcome) == [1, 2]
    assert all(c.score == round(c.score, 3) for c in outcome.items)


# --- BUG-01 / BUG-02: R1 (name of top is the best) and R2 (brand line), 03-plan §1 ---

DIACEREIN = [
    med(1, "Diacerein", "50 mg", "Diacerein"),
    med(2, "Diacerein 50 mg", "50 mg", "Diacerein"),
    med(3, "Konlemax", "50 mg", "Diacerein"),
]


def test_brand_line_best_match_required__R2():
    outcome, reader = run("KONLCMAX\nDiacerein 50mg\nSĐK: VD-12345-21", DIACEREIN)
    assert reader.fuzzy_calls == ["konlcmax"]
    assert outcome.status == S.LOW_CONFIDENCE
    assert outcome.preselected_id is None
    assert 3 in ids(outcome)  # the brand found by the fuzzy fallback stays selectable


def test_brand_line_without_any_candidate_blocks__R2():
    catalog = [med(1, "Diacerein", "50 mg", "Diacerein")]
    outcome, reader = run("XQZWVKTP\nDiacerein 50mg", catalog)
    assert reader.fuzzy_calls == ["xqzwvktp"]
    assert outcome.status == S.LOW_CONFIDENCE and outcome.preselected_id is None


def test_ingredient_spelling_variant_still_blocked__R2():
    # Catalog writes "Finasterid": the OCR line "finasteride" is no substring of it.
    catalog = [
        med(1, "Finasteride", "5 mg", "Finasterid"),
        med(2, "Flargos", "5 mg", "Finasteride"),
    ]
    outcome, _ = run("F1ARGOS\nFinasteride 5mg\nSĐK: VD-12345-21", catalog)
    assert outcome.status == S.LOW_CONFIDENCE and outcome.preselected_id is None
    assert 2 in ids(outcome)


def test_brand_containing_generic_name_blocked__R2():
    catalog = [
        med(1, "Acarbose 50mg", "50 mg", "Acarbose 50 mg"),
        med(2, "Acarsel 50", "50 mg", "Acarbose 50 mg"),
    ]
    outcome, _ = run("ACARSCL 50\nAcarbose 50 mg\nSĐK: VD-12345-21", catalog)
    assert outcome.status == S.LOW_CONFIDENCE and outcome.preselected_id is None
    assert set(ids(outcome)) == {1, 2}


def test_name_not_best_blocked_multiple_strengths__R1():
    catalog = [
        med(1, "Methylprednisolone", "4 mg", "Methylprednisolone"),
        med(2, "Methylprednisolone", "16 mg", "Methylprednisolon"),
        med(3, "Methylprednisolone Blue", "4 mg", "Methylprednisolone"),
    ]
    outcome, _ = run("METHYLPREDNISOLONE\nMethylprednisolone\nHộp 10 vỉ x 10 viên", catalog)
    assert outcome.status == S.LOW_CONFIDENCE and outcome.preselected_id is None
    assert R.MULTIPLE_STRENGTHS in outcome.reasons
    assert {1, 2} <= set(ids(outcome))


def test_generic_box_without_brand_line_still_matched():
    catalog = [med(1, "Paracetamol", "500 mg", "Paracetamol")]
    outcome, reader = run("PARACETAMOL 500MG\nParacetamol\nHSD 12/2027", catalog)
    assert reader.fuzzy_calls == []
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1


def test_brand_line_matching_top_still_matched__R2():
    catalog = [med(1, "Cefuroxim Kabi", "500 mg", "Cefuroxim"), med(2, "Cefuroxim", "250 mg")]
    outcome, _ = run("CEFUROXIM KABI 500mg\nCefuroxim Kabi", catalog)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1


def test_misread_name_that_finds_top_does_not_block__R2():
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol")]
    outcome, _ = run("PANAD0L 500mg\nParacetamol", catalog)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 1


def test_combination_ingredient_line_not_brand__R2():
    # "paracetamol caffeine" matches no ingredient as a substring, but is similar (0.739)
    # to "Paracetamol, Cafein": an ingredient line, not a brand line (AC1 unchanged).
    catalog = [med(10, "Panadol Extra", "500 mg + 65 mg", "Paracetamol, Cafein")]
    outcome, _ = run("PANADOL EXTRA\nParacetamol 500mg Caffeine 65mg", catalog)
    assert outcome.status == S.MATCHED and outcome.preselected_id == 10


def test_ingredient_line_threshold_from_settings__R2_AC10():
    catalog = [med(10, "Panadol Extra", "500 mg + 65 mg", "Paracetamol, Cafein")]
    strict = replace(POLICY, ingredient_line_similarity=1.0)
    outcome, _ = run("PANADOL EXTRA\nParacetamol 500mg Caffeine 65mg", catalog, policy=strict)
    assert outcome.status == S.LOW_CONFIDENCE and outcome.preselected_id is None
