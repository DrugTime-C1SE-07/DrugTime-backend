"""Use case tìm danh mục: tách từ, ghép số với đơn vị, escape wildcard của LIKE, giới hạn
(không cần DB). Ngữ nghĩa theo contract `GET /catalog/medications` (adhoc-20261116 B8)."""

import pytest

from drugtime.modules.catalog.application.search_medications import (
    MAX_SEARCH_TERMS,
    escape_like,
    search_medications,
    search_terms,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication

DRUG = CatalogMedication(1, "Amlodipin 5mg", "5 mg", "Viên nén", True, "Amlodipin besilat")


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, uow, terms, query, limit):
        self.calls.append((terms, query, limit))
        return [DRUG]


def test_trims_query_and_passes_limit():
    port = FakeSearch()
    assert search_medications(None, "  amlo  ", 7, port) == [DRUG]
    assert port.calls == [(["amlo"], "amlo", 7)]


@pytest.mark.parametrize(
    "raw, terms",
    [
        ("metformin 500 mg", ["metformin", "500mg"]),
        ("Metformin 500MG", ["metformin", "500mg"]),
        ("metformin  500 MG", ["metformin", "500mg"]),
        ("glucophage 500", ["glucophage", "500"]),
        ("0,5 g", ["0,5g"]),
        ("2.5 mcg", ["2.5mcg"]),
        ("10 ml", ["10ml"]),
        ("100 iu", ["100iu"]),
        ("5 %", ["5%"]),
        ("500 vien", ["500", "vien"]),
        ("mg 500", ["mg", "500"]),
    ],
)
def test_search_terms_merges_number_and_unit__AC12(raw, terms):
    assert search_terms(raw) == terms


def test_search_terms_collapses_whitespace_and_dedups__AC12():
    assert search_terms("  Thuốc \t ho  thuốc ") == ["thuốc", "ho"]
    assert search_terms("") == []
    many = " ".join(f"w{i}" for i in range(MAX_SEARCH_TERMS + 3))
    assert search_terms(many) == [f"w{i}" for i in range(MAX_SEARCH_TERMS)]


def test_search_terms_keeps_like_chars_literal__AC14():
    # Tách từ không hiểu wildcard; escape xảy ra sau, cho từng từ.
    assert search_terms("100% a_b a\\b") == ["100%", "a_b", "a\\b"]


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("50%", "50\\%"),
        ("a_b", "a\\_b"),
        ("a\\b", "a\\\\b"),
        ("\\%_", "\\\\\\%\\_"),
        ("thuốc ho", "thuốc ho"),  # dấu giữ nguyên (DB bỏ dấu)
    ],
)
def test_escapes_like_wildcards(raw, escaped):
    assert escape_like(raw) == escaped


def test_terms_and_query_reach_port_escaped__AC14():
    port = FakeSearch()
    search_medications(None, " 100%   a_b ", 20, port)
    # `query` (dùng để xếp hạng) là chuỗi đã gộp khoảng trắng, cũng đã escape.
    assert port.calls == [(["100\\%", "a\\_b"], "100\\% a\\_b", 20)]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_returns_empty_without_db(blank):
    port = FakeSearch()
    assert search_medications(None, blank, 20, port) == []
    assert port.calls == []
