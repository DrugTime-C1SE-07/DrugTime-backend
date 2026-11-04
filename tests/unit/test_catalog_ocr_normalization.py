"""Synthetic syntax/evidence regressions; no pharmaceutical accuracy claim."""

import builtins
import io
import socket
import unicodedata
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from drugtime.modules.catalog.application.normalize_ocr import (
    normalize_clean,
    normalize_key,
    normalize_ocr_text,
)


def test_line_sources_and_clean_key():
    raw = "  THUỐC ĐỎ\t \r\n\nMetformin\rMetformin\n"
    doc = normalize_ocr_text(raw)
    assert doc.raw_text == raw
    assert [line.line_id for line in doc.lines] == [1, 2, 3, 4, 5]
    assert [line.line_ending for line in doc.lines] == ["\r\n", "\n", "\r", "\n", ""]
    assert "".join(line.raw + line.line_ending for line in doc.lines) == raw
    for line in doc.lines:
        assert raw[line.raw_start : line.raw_end] == line.raw
        assert normalize_clean(line.clean) == line.clean
        assert normalize_key(line.key) == line.key
    assert doc.lines[0].clean == "thuốc đỏ"
    assert doc.lines[0].key == "thuoc do"
    assert normalize_ocr_text(unicodedata.normalize("NFD", "THUỐC ĐỎ")).lines[0].clean == "thuốc đỏ"
    with pytest.raises(FrozenInstanceError):
        doc.lines[0].key = "changed"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("500MG", "500 mg"),
        ("500 mg", "500 mg"),
        ("500.0mg", "500 mg"),
        ("0,5 g", "0.5 g"),
        ("0.5g", "0.5 g"),
        ("25 mcg", "25 mcg"),
        ("5mg/ml", "5 mg/ml"),
        ("250mg/5ml", "250 mg/5 ml"),
        ("500mg + 65mg", "500 mg + 65 mg"),
        ("0,9%", "0.9 %"),
    ],
)
def test_strength_whole_spans(text, expected):
    line = normalize_ocr_text("Thuốc Mẫu " + text).lines[0]
    assert line.name_key == "thuoc mau"
    (occurrence,) = line.strengths
    assert occurrence.canonical == expected
    assert line.key[occurrence.start : occurrence.end] == occurrence.source_text
    assert occurrence.line_id == 1
    assert not line.unparsed_strengths


@pytest.mark.parametrize(
    "text",
    [
        "-5mg",
        "- 500mg",
        "- 5 mg",
        "+5mg",
        "+ 500mg",
        "−500mg",
        "− 500mg",
        "0mg",
        "0.0 mg",
        "5OOmg",
        "1e3mg",
        "1e-3mg",
        "500mg +",
        "500mg + 5OOmg",
        "500mg + OOOmg",
        "500/65mg",
        "/500mg",
        "250mg/0ml",
        "250mg/-5ml",
        "250mg/5OOml",
        "250mg/",
        "250mg//5ml",
        "5 g/ml",
        "5 mcg/ml",
        "5 mg/g",
        "5 g + 5 mg",
        "500mg + 25mcg",
        "1,000 mg",
        "1.000 mg",
        "1,000,000 mg",
        "1.000.000 mg",
        "5.5.5mg",
        "50 IU",
        "50UI",
        "25 µg",
        "25μg",
        "5kg",
        "500mgg",
        "5 ml",
        "500mg,",
        "500mg.",
        "(500mg)",
        "500 mg,",
        "(500 mg)",
        "5/ml",
        "5 / ml",
    ],
)
def test_invalid_unsupported_whole_group(text):
    line = normalize_ocr_text("Thuốc Mẫu " + text).lines[0]
    assert not line.strengths
    assert line.unparsed_strengths
    assert line.name_key == line.key


@pytest.mark.parametrize("bad", ["O.5g", "O.5 g", "l0mg", "l0 mg", "5OOmg"])
@pytest.mark.parametrize("template", ["{bad}", "500mg {bad}", "{bad} 500mg"])
def test_valid_and_corrupted_groups_remain_separate(bad, template):
    line = normalize_ocr_text("Thuốc Mẫu " + template.format(bad=bad)).lines[0]
    assert line.unparsed_strengths
    assert normalize_key(bad) in line.name_key
    assert [o.canonical for o in line.strengths] == ([] if template == "{bad}" else ["500 mg"])


@pytest.mark.parametrize(
    "name", ["Vitamin B12", "Vitamin D3", "O0l1", "Metforrnin", "Long", "Log", "Ong"]
)
def test_names_and_confusables(name):
    line = normalize_ocr_text(name).lines[0]
    assert line.name_key == normalize_key(name)
    assert not line.strengths and not line.unparsed_strengths


@pytest.mark.parametrize(
    "raw,key,eligible",
    [
        ("Metformin 500mg viên nén hộp 10 vỉ", "metformin", True),
        ("SDK: VD-13882-11", "", False),
        ("SĐK VN-1234-56", "", False),
        ("sủi siro viên sủi 20 viên ®™•", "", False),
        ("Met.", "met.", False),
        ("Metform.", "metform.", False),
        ("B12", "b12", False),
        ("D3", "d3", False),
        ("5mg", "", False),
        ("Vienna Sirolex VD-X", "vienna sirolex vd-x", True),
        ("Số lô AB12, HSD 10/2027", "so lo ab12, hsd 10/2027", False),
        ("12345", "12345", False),
        ("Vitamin D3 5mg", "vitamin d3", True),
    ],
)
def test_whitelist_and_eligibility(raw, key, eligible):
    line = normalize_ocr_text(raw).lines[0]
    assert line.name_key == key
    assert line.query_eligible is eligible
    assert line.eligibility_reason
    assert line.raw == raw and line.key == normalize_key(raw)
    for span in line.removed_spans:
        assert line.key[span.start : span.end] == span.source_text


def test_evidence_retains_minority_unknown_and_repeated_occurrences():
    doc = normalize_ocr_text("Metformin 500mg\n" * 4 + "Metformin 850mg\n500mg 500.0mg\n5OOmg")
    evidence = doc.strength_evidence
    assert [(v.canonical, v.count) for v in evidence.values] == [("500 mg", 5), ("850 mg", 1)]
    assert len(evidence.values[0].occurrences) == 6
    assert evidence.has_conflict and evidence.has_unparsed
    assert not evidence.has_ambiguous_line
    assert len(evidence.unparsed) == 1
    tie = normalize_ocr_text("500mg\n850mg").strength_evidence
    assert [v.count for v in tie.values] == [1, 1]
    assert tie.has_conflict
    assert normalize_ocr_text("500mg 250mg").strength_evidence.has_ambiguous_line
    assert [v.canonical for v in normalize_ocr_text("0.5g\n500mg").strength_evidence.values] == [
        "0.5 g",
        "500 mg",
    ]


@pytest.mark.parametrize("text", ["", "  \t\n", "•®™", "\n", "5mg", "hop 10 vi"])
def test_empty_and_noise_no_query(text):
    doc = normalize_ocr_text(text)
    assert not any(line.query_eligible for line in doc.lines)
    assert not any(c.query_eligible for c in doc.clusters)
    if text == "":
        assert not doc.lines and not doc.clusters
    if text == "\n":
        assert len(doc.lines) == 2


@pytest.mark.parametrize("value", [None, 123, b"private-marker", ["private-marker"]])
def test_non_string_rejected_without_echo(value):
    with pytest.raises(TypeError, match="^OCR text must be a string$"):
        normalize_ocr_text(value)


def test_no_ocr_io_log_or_writes(monkeypatch, caplog, capsys):
    def reject(*args, **kwargs):
        raise AssertionError("Unexpected OCR I/O")

    with monkeypatch.context() as guard:
        for obj, attr in [(builtins, "open"), (io, "open"), (Path, "open"), (socket, "socket")]:
            guard.setattr(obj, attr, reject)
        doc = normalize_ocr_text("synthetic-private-marker 500mg\nsynthetic-private-marker 500mg")
    assert doc.clusters[0].count == 2
    assert "synthetic-private-marker" not in caplog.text + capsys.readouterr().out


@pytest.mark.parametrize("text", ["VD-X", "VD-12-34-extra", "ABCVD-12-34", "VD-12-34-56"])
def test_partial_registration_patterns_are_not_removed(text):
    line = normalize_ocr_text(text).lines[0]
    assert line.name_key == normalize_key(text)
    assert not line.removed_spans


def test_combination_is_one_vote_with_ordered_parts_and_uncertain_tail():
    doc = normalize_ocr_text("500mg + 65mg\n65mg + 500mg\n500mg + 5OOmg")
    assert [o.parts for line in doc.lines for o in line.strengths] == [
        ("500 mg", "65 mg"),
        ("65 mg", "500 mg"),
    ]
    assert len(doc.strength_evidence.values) == 2
    assert doc.strength_evidence.has_conflict and doc.strength_evidence.has_unparsed
    assert not doc.lines[2].strengths
