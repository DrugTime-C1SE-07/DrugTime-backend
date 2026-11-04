"""Clustering invariants with synthetic labels; raw calibration is tracked separately."""

import json
from itertools import permutations
from pathlib import Path

import pytest

from drugtime.modules.catalog.application.cluster_ocr_lines import cluster_ocr_lines
from drugtime.modules.catalog.application.normalize_ocr import normalize_ocr_text


def members(text, threshold=0.86):
    return [
        c.member_line_ids
        for c in cluster_ocr_lines(normalize_ocr_text(text).lines, threshold=threshold)
    ]


def test_exact_repeats_counts_order_and_representative():
    doc = normalize_ocr_text("Metformin\n METFORMIN \nMetformin bydrock.\nAspirin")
    assert doc.clusters[0].name_key == "metformin"
    assert doc.clusters[0].count == 2
    assert len(doc.clusters) == 3
    assert [c.cluster_id for c in doc.clusters] == [1, 3, 4]
    # At a permissive test threshold, exact support still wins over length.
    cluster = cluster_ocr_lines(doc.lines, threshold=0.65)[0]
    assert cluster.name_key == "metformin" and cluster.count == 3
    assert cluster.representative_line_id == 1


@pytest.mark.parametrize("threshold,expected", [(0.899, 1), (0.9, 1), (0.901, 2)])
def test_ratio_cutoff_below_equal_above(threshold, expected):
    assert len(members("abcdefghij\nabcdefgxij", threshold)) == expected


def test_complete_link_cannot_chain():
    result = members("aaaaaaaaaa\naaaaaaaabb\naaaaaabbbb", 0.8)
    assert result == [(1, 2), (3,)]


@pytest.mark.parametrize(
    "ordered",
    list(
        permutations(
            [
                "Candesartan Krka 16mg",
                "Candesartan Krka 160mg",
                "Candesartan Krka",
            ]
        )
    ),
)
def test_missing_strength_never_bridges_conflict(ordered):
    doc = normalize_ocr_text("\n".join(ordered))
    assert len(doc.clusters) == 3
    assert all(c.count == 1 for c in doc.clusters)
    assert sum(c.count for c in doc.clusters) == 3


def test_unique_missing_strength_attachment_and_unknown_vote():
    doc = normalize_ocr_text("Metformin 500mg\nMetformin\nMetformin 5OOmg\n500mg")
    assert doc.clusters[0].member_line_ids == (1, 2)
    assert doc.clusters[0].strength_evidence.values[0].count == 1
    assert all(4 not in c.member_line_ids for c in doc.clusters)
    assert doc.strength_evidence.values[0].count == 2
    assert doc.strength_evidence.has_unparsed


@pytest.mark.parametrize(
    "text",
    [
        "Vitamin B12\nVitamin D3",
        "Candesartan 16\nCandesartan 160",
        "Met.\nMetformin",
        "formin\nMetformin",
        "Metfor.\nMetform.",
    ],
)
def test_digits_substring_suffix_and_unanchored_fragments_stay_separate(text):
    assert len(members(text)) == 2


def test_fragment_prefix_guard_and_full_anchor():
    assert members("Metform.\nMetformin") == [(1, 2)]
    assert len(members("abcdefghijklm.\nabcdefghijklmnopqrst", 0.78)) == 1
    assert len(members("abcdefghijkl.\nabcdefghijklmnopqrst", 0.7)) == 2
    assert len(members("bcdefghijklm.\nabcdefghijklmnopqrst", 0.7)) == 2


def test_every_line_at_most_once_small_clusters_retained():
    doc = normalize_ocr_text("Metformin\nMetformim\nMetformin\nAspirin\nB12\n500mg\n")
    ids = [id_ for c in doc.clusters for id_ in c.member_line_ids]
    assert len(ids) == len(set(ids)) == 5
    assert any(not c.query_eligible for c in doc.clusters)
    assert [c.count for c in doc.clusters] == sorted([c.count for c in doc.clusters], reverse=True)


def test_equal_name_different_signatures_and_ambiguous_line():
    doc = normalize_ocr_text("Metformin 500mg\nMetformin 500mg 850mg\nMetformin 850mg")
    assert len(doc.clusters) == 3
    assert doc.strength_evidence.has_conflict
    assert doc.strength_evidence.has_ambiguous_line


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        cluster_ocr_lines((), threshold=threshold)


def test_synthetic_labelled_fixture():
    data = json.loads(
        (Path(__file__).parents[1] / "fixtures/catalog_ocr_clustering.json").read_text(
            encoding="utf-8"
        )
    )
    for sample in data["synthetic"]:
        actual = members(sample["raw_text"], data["selected_threshold"])
        assert actual == [tuple(ids) for ids in sample["expected_members"]], sample["id"]


_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/catalog_ocr_clustering.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("sample", _FIXTURE["real_labelled"], ids=lambda s: s["id"])
def test_labelled_real_raw_regression(sample):
    actual = any(set((1, 2)) <= set(ids) for ids in members(sample["raw_text"]))
    expected = sample["expected_same_cluster"]
    assert actual is expected, sample["id"]


def test_calibrated_threshold_and_provenance_are_fixed():
    from drugtime.modules.catalog.application.cluster_ocr_lines import CLUSTER_THRESHOLD

    assert CLUSTER_THRESHOLD == _FIXTURE["selected_threshold"] == 0.86
    assert len(_FIXTURE["real_labelled"]) == 4
    for sample in _FIXTURE["real_labelled"]:
        assert sample["label_status"] == "owner_confirmed"
        assert len(sample["source_sha256"]) == 64
        assert len(sample["source_line_ids"]) == 2
        assert sample["source_path"].startswith("datasets/results/pilot-002/raw/")
