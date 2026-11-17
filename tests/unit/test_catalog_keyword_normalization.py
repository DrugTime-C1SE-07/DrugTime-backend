"""SCRUM-166 / AC4: Unit tests for query handling in search_medications use case.

Cập nhật theo contract `GET /catalog/medications` của adhoc-20261116 (tìm theo từ):
- Tầng Python strip hai đầu và tách từ theo khoảng trắng (space, tab, xuống dòng); nhiều
  khoảng trắng bên trong tính như một (trước đây được giữ nguyên).
- Port nhận `terms` (từng từ, chữ thường, đã escape) và `query` (chuỗi đã gộp khoảng trắng,
  giữ chữ hoa/thường, đã escape) dùng để xếp hạng.
- Chuỗi rỗng hoặc chỉ khoảng trắng -> trả về [] ngay lập tức và không gọi catalog search.
- Ký tự đặc biệt của LIKE (% _ \\) được escape đúng bằng escape_like, cho từng từ.
- Dấu tiếng Việt, đ/Đ và dạng Unicode (NFC/NFD) được bảo toàn ở tầng Python để SQL
  catalog_search_key xử lý unaccent/lowercase.
"""

import unicodedata

import pytest

from drugtime.modules.catalog.application.search_medications import (
    escape_like,
    search_medications,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication

SAMPLE_MED = CatalogMedication(1, "Test Drug", "5mg", "Viên", True, "Test Active")


class FakeSearch:
    def __init__(self):
        self.calls: list[tuple[list[str], str, int]] = []

    def search(self, uow, terms: list[str], query: str, limit: int) -> list[CatalogMedication]:
        self.calls.append((terms, query, limit))
        return [SAMPLE_MED]


@pytest.mark.parametrize(
    "raw_query, expected_terms, expected_query",
    [
        # Strip khoảng trắng đầu / cuối (space, tab, newline)
        ("  paracetamol  ", ["paracetamol"], "paracetamol"),
        ("\tparacetamol\t", ["paracetamol"], "paracetamol"),
        ("\nparacetamol\n", ["paracetamol"], "paracetamol"),
        ("\r\n  paracetamol  \r\n", ["paracetamol"], "paracetamol"),
        # Khoảng trắng giữa chuỗi: tách từ, gộp thành một khoảng trắng
        ("para   cetamol", ["para", "cetamol"], "para cetamol"),
        ("Amlodipin  5mg", ["amlodipin", "5mg"], "Amlodipin 5mg"),
        ("  para   cetamol  ", ["para", "cetamol"], "para cetamol"),
        ("Thuốc   ho   Bảo   Thanh", ["thuốc", "ho", "bảo", "thanh"], "Thuốc ho Bảo Thanh"),
        ("  Thuốc   ho   Bảo   Thanh  ", ["thuốc", "ho", "bảo", "thanh"], "Thuốc ho Bảo Thanh"),
        ("Đồng  sulfat", ["đồng", "sulfat"], "Đồng sulfat"),
        # Tab / xuống dòng giữa chuỗi cũng là khoảng trắng tách từ
        ("para\tcetamol", ["para", "cetamol"], "para cetamol"),
        ("  para\tcetamol  ", ["para", "cetamol"], "para cetamol"),
        ("para\n\tcetamol", ["para", "cetamol"], "para cetamol"),
        # Từ chữ thường; `query` giữ chữ hoa/thường và dấu tiếng Việt
        ("PARACETAMOL", ["paracetamol"], "PARACETAMOL"),
        ("  PARACETAMOL  ", ["paracetamol"], "PARACETAMOL"),
        ("Paracetamol 500mg", ["paracetamol", "500mg"], "Paracetamol 500mg"),
        ("Paracetamol 500 mg", ["paracetamol", "500mg"], "Paracetamol 500 mg"),
        ("Thuốc ho Bảo Thanh", ["thuốc", "ho", "bảo", "thanh"], "Thuốc ho Bảo Thanh"),
        ("Đồng sulfat", ["đồng", "sulfat"], "Đồng sulfat"),
        ("đông y", ["đông", "y"], "đông y"),
    ],
)
def test_search_medications_strips_ends_and_splits_words__AC4(
    raw_query: str, expected_terms: list[str], expected_query: str
):
    """AC4 (contract adhoc-20261116): strip 2 đầu, tách từ, gộp khoảng trắng bên trong."""
    port = FakeSearch()
    result = search_medications(None, raw_query, 20, port)
    assert result == [SAMPLE_MED]
    assert port.calls == [(expected_terms, expected_query, 20)]


@pytest.mark.parametrize(
    "blank_query",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        "\r\n",
        " \t \n \r  ",
    ],
)
def test_search_medications_blank_returns_empty_list_without_calling_port(blank_query: str):
    """Chuỗi rỗng hoặc chỉ khoảng trắng trả về [] ngay lập tức và không gọi catalog search."""
    port = FakeSearch()
    result = search_medications(None, blank_query, 20, port)
    assert result == []
    assert port.calls == []


@pytest.mark.parametrize(
    "raw_query, expected_terms, expected_query",
    [
        ("50%", ["50\\%"], "50\\%"),
        ("  50%  ", ["50\\%"], "50\\%"),
        ("a_b", ["a\\_b"], "a\\_b"),
        ("a\\b", ["a\\\\b"], "a\\\\b"),
        ("  100%   tự   nhiên  ", ["100\\%", "tự", "nhiên"], "100\\% tự nhiên"),
        ("a_b  c\\d", ["a\\_b", "c\\\\d"], "a\\_b c\\\\d"),
        ("\\%_", ["\\\\\\%\\_"], "\\\\\\%\\_"),
    ],
)
def test_search_medications_escapes_like_wildcards_correctly(
    raw_query: str, expected_terms: list[str], expected_query: str
):
    """Ký tự đặc biệt của LIKE (% _ \\) được escape đúng ở từng từ và ở chuỗi xếp hạng."""
    port = FakeSearch()
    search_medications(None, raw_query, 15, port)
    assert port.calls == [(expected_terms, expected_query, 15)]


@pytest.mark.parametrize("raw", ["50%", "a_b", "a\\b"])
def test_escape_like_is_reused_for_each_term(raw: str):
    port = FakeSearch()
    search_medications(None, raw, 20, port)
    assert port.calls[0][0] == [escape_like(raw)]


@pytest.mark.parametrize(
    "base_text",
    [
        "Thuốc ho Bảo Thanh",
        "Đồng sulfat",
        "Paracetamol 500mg",
    ],
)
def test_search_medications_preserves_unicode_nfc_and_nfd(base_text: str):
    """Tầng Python bảo toàn dạng Unicode (NFC/NFD), không tự chuẩn hóa; DB bỏ dấu."""
    for form in ("NFC", "NFD"):
        text = unicodedata.normalize(form, base_text)
        port = FakeSearch()
        search_medications(None, f"  {text}  ", 20, port)
        assert port.calls == [([w.lower() for w in text.split()], text, 20)]
