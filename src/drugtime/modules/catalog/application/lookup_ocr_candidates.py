"""Retrieve every eligible cluster without catalog snapshots or medication scoring."""

from collections import Counter
from typing import Protocol

from drugtime.modules.catalog.domain.catalog_index import (
    CatalogQueryResult,
    MatchKind,
    MatchSource,
    NormalizedOcrText,
    OcrCatalogCandidate,
    OcrCatalogCluster,
    OcrCatalogLookup,
    QueryCoverage,
)
from drugtime.shared.uow import UnitOfWork


class OcrCandidateReader(Protocol):
    def find_ocr_matches(
        self, uow: UnitOfWork, query_key: str, kind: MatchKind, *, limit: int = 200
    ) -> CatalogQueryResult: ...


def lookup_ocr_candidates(
    uow: UnitOfWork, normalized: NormalizedOcrText, reader: OcrCandidateReader
) -> OcrCatalogLookup:
    """Reuse query results only inside this invocation; propagate all read failures."""
    lines = {line.line_id: line for line in normalized.lines}
    queried = {}
    groups, coverage = [], []
    for cluster in normalized.clusters:
        members = [lines[line_id] for line_id in cluster.member_line_ids]
        counts = Counter(line.name_key for line in members if line.query_eligible)
        keys = sorted(counts, key=lambda key: (-counts[key], key))
        if cluster.query_eligible:
            keys.remove(cluster.name_key)
            keys.insert(0, cluster.name_key)
        candidates, sources = {}, {}
        for key in keys:
            line_ids = tuple(
                line.line_id for line in members if line.name_key == key and line.query_eligible
            )
            for kind in MatchKind:
                pair = (key, kind)
                if pair not in queried:
                    queried[pair] = reader.find_ocr_matches(uow, key, kind)
                result = queried[pair]
                coverage.append(QueryCoverage(cluster.cluster_id, key, kind, result.truncated))
                for hit in result.hits:
                    med_id = hit.medication.id
                    candidates[med_id] = hit.medication
                    source = MatchSource(
                        key,
                        cluster.cluster_id,
                        line_ids,
                        kind,
                        hit.alias_id,
                        hit.alias_text,
                        hit.active_ingredient_id,
                    )
                    bucket = sources.setdefault(med_id, [])
                    if source not in bucket:
                        bucket.append(source)
        groups.append(
            OcrCatalogCluster(
                cluster.cluster_id,
                tuple(
                    OcrCatalogCandidate(candidates[id_], tuple(sources[id_]))
                    for id_ in sorted(candidates)
                ),
            )
        )
    return OcrCatalogLookup(normalized, tuple(groups), tuple(coverage))
