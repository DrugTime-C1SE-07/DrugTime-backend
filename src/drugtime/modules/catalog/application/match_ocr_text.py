"""Suggest catalog medications for the OCR text of one scan (PB31, task 4.13).

The text is never stored and never logged (QD-39, QD-33): only status, top score,
candidate count, reason codes and elapsed time are logged.
"""

import logging
import time
from typing import Protocol

from drugtime.modules.catalog.application.lookup_ocr_candidates import (
    OcrCandidateReader,
    lookup_ocr_candidates,
)
from drugtime.modules.catalog.application.normalize_ocr import normalize_ocr_text
from drugtime.modules.catalog.application.score_ocr_matches import score_ocr_matches
from drugtime.modules.catalog.domain.catalog_index import OcrCatalogLookup
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.domain.ocr_match import (
    FuzzyHit,
    FuzzyLookup,
    MatchPolicy,
    OcrMatchOutcome,
)
from drugtime.shared.uow import UnitOfWork

_LOG = logging.getLogger(__name__)


class OcrMatchReader(OcrCandidateReader, Protocol):
    def find_fuzzy_name_matches(
        self, uow: UnitOfWork, query_key: str, *, threshold: float, limit: int
    ) -> tuple[tuple[CatalogMedication, ...], bool]: ...


def _keys_without_hits(lookup: OcrCatalogLookup) -> list[tuple[int, str]]:
    """(cluster, key) pairs that were queried but found nothing in any kind (B5)."""
    hit_keys = {
        (source.cluster_id, source.query_key)
        for cluster in lookup.clusters
        for candidate in cluster.candidates
        for source in candidate.sources
    }
    seen, empty = set(), []
    for coverage in lookup.coverage:
        pair = (coverage.cluster_id, coverage.query_key)
        if pair not in hit_keys and pair not in seen:
            seen.add(pair)
            empty.append(pair)
    return empty


def _fuzzy(
    uow: UnitOfWork, lookup: OcrCatalogLookup, reader: OcrMatchReader, policy: MatchPolicy
) -> FuzzyLookup:
    lines = {line.line_id: line for line in lookup.normalized.lines}
    clusters = {c.cluster_id: c for c in lookup.normalized.clusters}
    queried: dict[str, tuple[tuple[CatalogMedication, ...], bool]] = {}
    hits, truncated = [], False
    for cluster_id, key in _keys_without_hits(lookup):
        if key not in queried:
            queried[key] = reader.find_fuzzy_name_matches(
                uow, key, threshold=policy.fuzzy_similarity, limit=policy.fuzzy_limit
            )
        found, cut = queried[key]
        truncated |= cut
        line_ids = tuple(
            line_id
            for line_id in clusters[cluster_id].member_line_ids
            if lines[line_id].query_eligible and lines[line_id].name_key == key
        )
        hits.extend(FuzzyHit(med, key, cluster_id, line_ids) for med in found)
    return FuzzyLookup(tuple(hits), truncated)


def match_ocr_text(
    uow: UnitOfWork,
    text: str,
    *,
    limit: int,
    policy: MatchPolicy,
    reader: OcrMatchReader,
) -> OcrMatchOutcome:
    started = time.perf_counter()
    normalized = normalize_ocr_text(text)
    lookup = lookup_ocr_candidates(uow, normalized, reader)
    outcome = score_ocr_matches(lookup, _fuzzy(uow, lookup, reader, policy), policy, limit)
    _LOG.info(
        "ocr_match status=%s top_score=%s candidates=%d reasons=%s elapsed_ms=%d",
        outcome.status.value,
        "none" if outcome.top_score is None else f"{outcome.top_score:.3f}",
        len(outcome.items),
        ",".join(sorted(r.value for r in outcome.reasons)) or "none",
        round((time.perf_counter() - started) * 1000),
    )
    return outcome
