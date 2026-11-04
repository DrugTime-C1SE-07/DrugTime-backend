"""Pure values of OCR matching (4.13): trigram parity, strength comparison, policy limits."""

import pytest

from drugtime.modules.catalog.application.normalize_ocr import normalize_ocr_text
from drugtime.modules.catalog.domain.ocr_match import (
    MatchPolicy,
    OcrMatchReason,
    strength_parts,
    trigram_similarity,
)
from drugtime.shared.config import Settings

# Measured with pg_trgm 1.6 `similarity()` on local Supabase (evidence/plan-trigram-probe.log).
PG_TRGM_SAMPLES = [
    ("panad0l", "panadol", 0.454545),
    ("panad0l", "panadol extra", 0.294118),
    ("panad0l extra", "panadol extra", 0.647059),
    ("paracetam0l", "paracetamol", 0.6),
    ("cefur0xim", "cefuroxim", 0.538462),
    ("amoxici11in", "amoxicillin", 0.5),
    ("panadol", "panadol extra", 0.571429),
    ("losec", "lasix", 0.0909091),
    ("celebrex", "celexa", 0.333333),
    ("losartan", "lostatin", 0.2),
    ("hsd 12/2027 lo 123", "panadol", 0.0),
]


@pytest.mark.parametrize("a,b,expected", PG_TRGM_SAMPLES)
def test_trigram_similarity_matches_pg_trgm_samples(a, b, expected):
    assert trigram_similarity(a, b) == pytest.approx(expected, abs=1e-5)
    assert trigram_similarity(b, a) == pytest.approx(expected, abs=1e-5)


def test_trigram_similarity_edges():
    assert trigram_similarity("", "") == 0.0
    assert trigram_similarity("panadol", "") == 0.0
    assert trigram_similarity("panadol", "PANADOL") == 1.0


def parts(text):
    return strength_parts(normalize_ocr_text(text).strength_evidence)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("500 mg", {"500 mg"}),
        ("500mg", {"500 mg"}),
        ("0,5 g", {"500 mg"}),
        ("0.5g", {"500 mg"}),
        ("1 g", {"1000 mg"}),
        ("500 mcg", {"0.5 mg"}),
        ("500 mg + 65 mg", {"500 mg", "65 mg"}),
        ("Paracetamol 500mg Caffeine 65mg", {"500 mg", "65 mg"}),
        ("0,1 %", {"0.1 %"}),
        ("250 mg/5 ml", {"250 mg/5 ml"}),
        ("60mg/ml", {"60 mg/ml"}),
    ],
)
def test_strength_parts_mass_conversion_only__AC19(text, expected):
    assert parts(text) == frozenset(expected)


@pytest.mark.parametrize("text", ["5 ml", "2.000.000 IU", "", "HSD 12/2027"])
def test_strength_parts_not_converted_across_dimensions__AC19(text):
    # ml/IU are never turned into mg (QD-38); they are not a parsed strength at all.
    assert parts(text) == frozenset()


def test_ml_is_reported_as_unparsed_evidence__AC19():
    evidence = normalize_ocr_text("Siro 5 ml").strength_evidence
    assert evidence.has_unparsed and not evidence.values


def test_reason_codes_match_contract():
    assert {r.value for r in OcrMatchReason} == {
        "strength_unverified",
        "strength_unparsed",
        "multiple_strengths",
        "strength_conflict",
        "strength_mismatch",
        "lasa_close",
        "tie",
        "truncated",
        "below_threshold",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"low_threshold": 0.8, "threshold": 0.7},
        {"threshold": 1.2},
        {"margin": -0.1},
        {"weight_name": -0.1, "weight_strength": 0.9},
        {"weight_name": 0.6},
        {"weight_name": float("nan")},
        {"default_limit": 0},
        {"default_limit": 11},
        {"fuzzy_limit": 0},
        {"fuzzy_similarity": 1.5},
        {"ingredient_line_similarity": -0.1},
        {"ingredient_line_similarity": 1.1},
    ],
)
def test_match_policy_rejects_invalid_config(kwargs):
    with pytest.raises(ValueError):
        MatchPolicy(**kwargs)


def test_policy_defaults_follow_requirement():
    policy = MatchPolicy.from_settings(Settings(_env_file=None))
    assert (policy.threshold, policy.low_threshold, policy.margin) == (0.7, 0.4, 0.05)
    assert policy.default_limit == 5
    assert policy.weights == (0.5, 0.3, 0.15, 0.05)
    assert (policy.fuzzy_similarity, policy.fuzzy_limit) == (0.3, 50)
    assert policy.ingredient_line_similarity == 0.6


def test_policy_from_settings_uses_env__AC10(monkeypatch):
    monkeypatch.setenv("OCR_MATCH_THRESHOLD", "0.8")
    monkeypatch.setenv("OCR_MATCH_DEFAULT_LIMIT", "3")
    policy = MatchPolicy.from_settings(Settings(_env_file=None))
    assert policy.threshold == 0.8
    assert policy.default_limit == 3
