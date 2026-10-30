"""Deterministic complete-link clustering; counts describe lines, never confidence."""

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import cache

from drugtime.modules.catalog.domain.catalog_index import OcrCluster, OcrLine, summarize_strengths

# Selected from five thresholds using four owner-labelled raw pairs plus synthetic boundaries.
# Small calibration set only; this is not medication-matching confidence or accuracy.
CLUSTER_THRESHOLD = 0.86


def cluster_ocr_lines(
    lines: tuple[OcrLine, ...], *, threshold: float = CLUSTER_THRESHOLD
) -> tuple[OcrCluster, ...]:
    if not 0 <= threshold <= 1:
        raise ValueError("Cluster threshold must be between zero and one")

    @cache
    def pair_ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b, autojunk=False).ratio()

    def ratio(a: str, b: str) -> float:
        return pair_ratio(*sorted((a, b)))

    def comparable(a: OcrLine, b: OcrLine) -> float:
        if a.name_key == b.name_key:
            return 1.0

        def number_tokens(s: str) -> tuple[str, ...]:
            return tuple(re.findall(r"\b\w*\d\w*\b", s))

        if number_tokens(a.name_key) != number_tokens(b.name_key):
            return -1.0
        if a.query_eligible and b.query_eligible:
            return ratio(a.name_key, b.name_key)
        # An ineligible fragment needs a full eligible anchor, never another fragment.
        fragment, anchor = (a, b) if not a.query_eligible else (b, a)
        if not anchor.query_eligible or not re.fullmatch(r"[a-z]{3,}\.", fragment.name_key):
            return -1.0
        prefix = fragment.name_key[:-1]
        if not any(
            token.startswith(prefix) and len(prefix) / len(token) >= 0.65
            for token in anchor.name_key.split()
        ):
            return -1.0
        return ratio(prefix, anchor.name_key)

    def score(left: list[OcrLine], right: list[OcrLine]) -> float:
        return min(comparable(a, b) for a in left for b in right)

    def merge(groups: list[list[OcrLine]]) -> list[list[OcrLine]]:
        clusters: list[list[OcrLine]] = []
        for group in sorted(groups, key=lambda g: (-len(g), g[0].name_key, g[0].line_id)):
            matches = [
                (score(group, c), min(line.line_id for line in c), i)
                for i, c in enumerate(clusters)
            ]
            matches = [m for m in matches if m[0] >= threshold]
            if matches:
                _, _, index = min(matches, key=lambda m: (-m[0], m[1]))
                clusters[index].extend(group)
            else:
                clusters.append(list(group))
        return clusters

    signatures = defaultdict(lambda: defaultdict(list))
    for line in lines:
        if line.name_key and any(c.isalnum() for c in line.name_key):
            signature = tuple(sorted({o.canonical for o in line.strengths}))
            signatures[signature][line.name_key].append(line)
    complete = []
    for signature in sorted(s for s in signatures if s):
        complete.extend(merge(list(signatures[signature].values())))
    # Decide unique attachment against strength-bearing clusters only. Missing-strength
    # groups never merge two incompatible clusters, and are not new attachment anchors.
    remaining = []
    attachments = []
    for group in signatures[()].values():
        matches = [i for i, c in enumerate(complete) if score(group, c) >= threshold]
        if len(matches) == 1:
            attachments.append((matches[0], group))
        else:
            remaining.append(group)
    # Multiple missing groups must still satisfy complete-link after attachment.
    for index, group in sorted(attachments, key=lambda v: (-len(v[1]), v[1][0].name_key)):
        if score(group, complete[index]) >= threshold:
            complete[index].extend(group)
        else:
            remaining.append(group)
    complete.extend(merge(remaining))
    result = []
    for cluster in complete:
        members = tuple(sorted(cluster, key=lambda line: line.line_id))
        counts = Counter(line.name_key for line in members)
        eligible = [line for line in members if line.query_eligible]
        representative = min(
            eligible or list(members),
            key=lambda line: (
                -counts[line.name_key],
                -sum(ratio(line.name_key, other.name_key) for other in members),
                -len(line.name_key),
                line.line_id,
            ),
        )
        result.append(
            OcrCluster(
                members[0].line_id,
                tuple(line.line_id for line in members),
                len(members),
                representative.line_id,
                representative.name_key,
                bool(eligible),
                summarize_strengths(members),
            )
        )
    return tuple(sorted(result, key=lambda c: (-c.count, c.cluster_id, c.name_key)))
