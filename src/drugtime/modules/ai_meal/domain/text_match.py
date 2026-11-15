"""Khớp chuỗi tiếng Việt cho bộ lọc phòng thủ (task 4.26, AC6c, AC6d).

Không phân biệt hoa thường, bỏ dấu, khớp theo ranh giới từ để "ga" không khớp "gạo".
Đây không phải kiểm tra tương tác: kết luận thuốc–thực phẩm vẫn do engine tất định.
"""

import re
import unicodedata
from collections.abc import Iterable

_SPACES = re.compile(r"\s+")
# Tách câu `food_to_avoid` tự do ("Thực phẩm giàu kali (chuối, cam)") thành từ khóa.
_SEPARATORS = re.compile(r"[,;()/\[\]]|\s+(?:và|hoặc|hay)\s+", re.IGNORECASE)
_MIN_KEYWORD = 2


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _SPACES.sub(" ", stripped).strip().lower()


def keywords(phrases: Iterable[str]) -> tuple[str, ...]:
    """Từ khóa đã chuẩn hóa, gồm cả cụm đầy đủ và từng phần tách theo dấu câu/"và"/"hoặc"."""
    found: set[str] = set()
    for phrase in phrases:
        for part in (phrase, *_SEPARATORS.split(phrase)):
            key = normalize(part or "")
            if len(key) >= _MIN_KEYWORD:
                found.add(key)
    return tuple(sorted(found))


# Từ đầu của tên muối/khoáng chất: không dùng làm "tên gốc" của thuốc, vì cũng là chất dinh dưỡng
# hay xuất hiện trong lợi ích món ăn ("Ít kali", "Giàu canxi").
_NUTRIENT_WORDS = frozenset(
    {"natri", "kali", "calci", "canxi", "magie", "magnesi", "vitamin", "acid", "axit", "kem",
     "sodium", "potassium", "calcium", "magnesium", "zinc", "iron"}
)
_MIN_BASE_NAME = 4


def base_names(names: Iterable[str]) -> tuple[str, ...]:
    """Tên gốc đã chuẩn hóa của thuốc: từ đầu tiên sau khi bỏ hàm lượng.

    "Losartan kali" → "losartan"; "Cozaar 50mg" → "cozaar"; "Natri clorid" → không có.
    """
    found: set[str] = set()
    for name in names:
        words = [w for w in normalize(name).split() if not any(c.isdigit() for c in w)]
        if words and len(words[0]) >= _MIN_BASE_NAME and words[0] not in _NUTRIENT_WORDS:
            found.add(words[0])
    return tuple(sorted(found))


def contains_any(text: str, normalized_keywords: Iterable[str]) -> bool:
    haystack = normalize(text)
    return any(
        re.search(rf"(?<!\w){re.escape(k)}(?!\w)", haystack) for k in normalized_keywords
    )
