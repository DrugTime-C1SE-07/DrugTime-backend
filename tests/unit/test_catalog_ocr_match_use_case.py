"""Orchestration of OCR matching (4.13): fuzzy fallback (B5) and metadata-only logging (AC7)."""

import logging

from drugtime.modules.catalog.application.match_ocr_text import match_ocr_text
from drugtime.modules.catalog.domain.ocr_match import MatchPolicy
from tests.unit.test_catalog_ocr_match_scoring import FakeReader, med

SENTINEL = "Zyqoxatriptan"


def test_fuzzy_only_for_keys_without_hits__AC17():
    catalog = [med(1, "Panadol", "500 mg", "Paracetamol")]
    reader = FakeReader(catalog)
    outcome = match_ocr_text(
        None, "PANAD0L 500mg\nParacetamol\nPanadol", limit=5, policy=MatchPolicy(), reader=reader
    )
    # "panadol" and "paracetamol" have substring hits; only the misread key goes fuzzy, once.
    assert reader.fuzzy_calls == ["panad0l"]
    assert [c.medication.id for c in outcome.items] == [1]


def test_misread_name_found_by_fuzzy_only__AC17():
    reader = FakeReader([med(1, "Panadol", "500 mg"), med(2, "Amlodipin", "5 mg")])
    outcome = match_ocr_text(None, "PANAD0L", limit=5, policy=MatchPolicy(), reader=reader)
    assert reader.fuzzy_calls == ["panad0l"]
    assert [c.medication.id for c in outcome.items] == [1]


def test_fuzzy_uses_policy_threshold_and_limit():
    calls = []

    class Reader(FakeReader):
        def find_fuzzy_name_matches(self, uow, query_key, *, threshold, limit):
            calls.append((threshold, limit))
            return super().find_fuzzy_name_matches(uow, query_key, threshold=threshold, limit=limit)

    policy = MatchPolicy(fuzzy_similarity=0.45, fuzzy_limit=7)
    match_ocr_text(None, "PANAD0L", limit=5, policy=policy, reader=Reader([med(1, "Panadol")]))
    assert calls == [(0.45, 7)]


def test_no_fuzzy_when_nothing_eligible():
    reader = FakeReader([med(1, "Panadol")])
    match_ocr_text(None, "HSD 12/2027\n123", limit=5, policy=MatchPolicy(), reader=reader)
    assert reader.fuzzy_calls == []


def test_ocr_text_never_logged__AC7(caplog):
    reader = FakeReader([med(1, SENTINEL, "10 mg", "Hoat chat " + SENTINEL)])
    caplog.set_level(logging.DEBUG)
    match_ocr_text(
        None, f"{SENTINEL} 10mg\n{SENTINEL.lower()}", limit=5, policy=MatchPolicy(), reader=reader
    )
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert SENTINEL.lower() not in text.lower()
    lines = [r for r in caplog.records if r.getMessage().startswith("ocr_match ")]
    assert len(lines) == 1
    message = lines[0].getMessage()
    for field in ("status=", "top_score=", "candidates=", "reasons=", "elapsed_ms="):
        assert field in message
