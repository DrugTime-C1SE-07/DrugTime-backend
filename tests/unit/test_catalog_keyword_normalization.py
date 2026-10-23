"""SCRUM-166 / AC4: Unit tests for query handling in search_medications use case.

Tham chiếu AC4 (test_internal_whitespace_is_preserved__AC4):
- Tầng Python chỉ thực hiện strip hai đầu (kể cả tab, xuống dòng).
- Khoảng trắng bên trong chuỗi ĐƯỢC GIỮ NGUYÊN (không gộp \\s+ thành một khoảng trắng).
- Chuỗi rỗng hoặc chỉ khoảng trắng -> trả về [] ngay lập tức và không gọi catalog search.
- Ký tự đặc biệt của LIKE (% _ \\) được escape đúng bằng escape_like.
- Dấu tiếng Việt, đ/Đ, chữ hoa/thường và dạng Unicode (NFC/NFD) được bảo toàn nguyên vẹn
  ở tầng Python để chuyển xuống SQL catalog_search_key xử lý unaccent/lowercase.
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
        self.calls: list[tuple[str, int]] = []

    def search(self, uow, escaped: str, limit: int) -> list[CatalogMedication]:
        self.calls.append((escaped, limit))
        return [SAMPLE_MED]


@pytest.mark.parametrize(
    "raw_query, expected_escaped",
    [
        # Strip khoảng trắng đầu / cuối (space, tab, newline)
        ("  paracetamol  ", "paracetamol"),
        ("\tparacetamol\t", "paracetamol"),
        ("\nparacetamol\n", "paracetamol"),
        ("\r\n  paracetamol  \r\n", "paracetamol"),
        # AC4: Khoảng trắng giữa chuỗi ĐƯỢC GIỮ NGUYÊN
        ("para   cetamol", "para   cetamol"),
        ("Amlodipin  5mg", "Amlodipin  5mg"),
        ("  para   cetamol  ", "para   cetamol"),
        ("Thuốc   ho   Bảo   Thanh", "Thuốc   ho   Bảo   Thanh"),
        ("  Thuốc   ho   Bảo   Thanh  ", "Thuốc   ho   Bảo   Thanh"),
        ("Đồng  sulfat", "Đồng  sulfat"),
        # Tab / xuống dòng giữa chuỗi cũng được giữ nguyên (chỉ strip 2 đầu)
        ("para\tcetamol", "para\tcetamol"),
        ("  para\tcetamol  ", "para\tcetamol"),
        ("para\n\tcetamol", "para\n\tcetamol"),
        # Casing và dấu tiếng Việt được giữ nguyên ở tầng Python
        ("PARACETAMOL", "PARACETAMOL"),
        ("  PARACETAMOL  ", "PARACETAMOL"),
        ("Paracetamol 500mg", "Paracetamol 500mg"),
        ("Thuốc ho Bảo Thanh", "Thuốc ho Bảo Thanh"),
        ("Đồng sulfat", "Đồng sulfat"),
        ("đông y", "đông y"),
    ],
)
def test_search_medications_strips_ends_and_preserves_internal_whitespace_and_casing__AC4(
    raw_query: str, expected_escaped: str
):
    """AC4: search_medications strip 2 đầu nhưng giữ nguyên khoảng trắng và ký tự bên trong."""
    port = FakeSearch()
    result = search_medications(None, raw_query, 20, port)
    assert result == [SAMPLE_MED]
    assert port.calls == [(expected_escaped, 20)]


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
    "raw_query, expected_escaped",
    [
        ("50%", "50\\%"),
        ("  50%  ", "50\\%"),
        ("a_b", "a\\_b"),
        ("a\\b", "a\\\\b"),
        ("  100%   tự   nhiên  ", "100\\%   tự   nhiên"),
        ("a_b  c\\d", "a\\_b  c\\\\d"),
        ("\\%_", "\\\\\\%\\_"),
    ],
)
def test_search_medications_escapes_like_wildcards_correctly(
    raw_query: str, expected_escaped: str
):
    """Ký tự đặc biệt của LIKE (% _ \\) được escape đúng, đồng thời bảo toàn khoảng trắng bên trong."""
    port = FakeSearch()
    search_medications(None, raw_query, 15, port)
    assert port.calls == [(expected_escaped, 15)]


@pytest.mark.parametrize(
    "base_text",
    [
        "Thuốc ho Bảo Thanh",
        "Đồng sulfat",
        "Paracetamol 500mg",
    ],
)
def test_search_medications_preserves_unicode_nfc_and_nfd(base_text: str):
    """Tầng Python bảo toàn dạng Unicode (NFC/NFD) của chuỗi, không tự ý chuyển đổi."""
    nfc = unicodedata.normalize("NFC", base_text)
    nfd = unicodedata.normalize("NFD", base_text)

    port_nfc = FakeSearch()
    search_medications(None, f"  {nfc}  ", 20, port_nfc)
    assert port_nfc.calls == [(nfc, 20)]

    port_nfd = FakeSearch()
    search_medications(None, f"  {nfd}  ", 20, port_nfd)
    assert port_nfd.calls == [(nfd, 20)]
