"""Use case tìm danh mục: trim, escape wildcard của LIKE, giới hạn (không cần DB)."""

import pytest

from drugtime.modules.catalog.application.search_medications import (
    escape_like,
    search_medications,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication

DRUG = CatalogMedication(1, "Amlodipin 5mg", "5 mg", "Viên nén", True, "Amlodipin besilat")


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, uow, escaped, limit):
        self.calls.append((escaped, limit))
        return [DRUG]


def test_trims_query_and_passes_limit():
    port = FakeSearch()
    assert search_medications(None, "  amlo  ", 7, port) == [DRUG]
    assert port.calls == [("amlo", 7)]


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("50%", "50\\%"),
        ("a_b", "a\\_b"),
        ("a\\b", "a\\\\b"),
        ("\\%_", "\\\\\\%\\_"),
        ("thuốc ho", "thuốc ho"),  # dấu và khoảng trắng bên trong giữ nguyên (DB bỏ dấu)
    ],
)
def test_escapes_like_wildcards(raw, escaped):
    assert escape_like(raw) == escaped


def test_escaped_query_reaches_port():
    port = FakeSearch()
    search_medications(None, " 100% ", 20, port)
    assert port.calls == [("100\\%", 20)]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_returns_empty_without_db(blank):
    port = FakeSearch()
    assert search_medications(None, blank, 20, port) == []
    assert port.calls == []
