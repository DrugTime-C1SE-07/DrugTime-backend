"""Pure OCR keys and conservative strength parsing; no medicine is inferred or selected."""

import re
import string
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from drugtime.modules.catalog.application.cluster_ocr_lines import cluster_ocr_lines
from drugtime.modules.catalog.domain.catalog_index import (
    NormalizedOcrText,
    OcrLine,
    RemovedSpan,
    StrengthOccurrence,
    StrengthStatus,
    summarize_strengths,
)

_DIACRITICS = str.maketrans({"đ": "d", "Đ": "d"})
_NUMBER = r"[0-9]+(?:[.,][0-9]+)?"
_SIMPLE = re.compile(rf"({_NUMBER})\s*(mcg|mg|g|%)")
_CONCENTRATION = re.compile(rf"({_NUMBER})\s*mg\s*/\s*(?:({_NUMBER})\s*)?ml")
_COMBINATION = re.compile(rf"{_NUMBER}\s*mg(?:\s*\+\s*{_NUMBER}\s*mg)+")
_MG_PART = re.compile(rf"({_NUMBER})\s*mg")
_GROUPING = re.compile(r"[1-9][0-9]{0,2}(?:[.,][0-9]{3})+")
_TOKENS = re.compile(r"[+/]|[^\s+/]+")
# Detection also accepts an OCR-confusable prefix followed by a real digit. Keep
# this separate from _NUMBER: it signals uncertainty, never repairs or parses it.
# Requiring a digit avoids treating words such as "long" or "log" as amounts.
_AMOUNT_LIKE = r"[-−﹣－]?(?:[0-9][\w.,-]*|[ol][ol.,-]*[0-9][0-9ol.,-]*)"
_NUMBER_LIKE = re.compile(_AMOUNT_LIKE)
# A strength-looking unit outside the grammar is retained, never converted to a supported one.
_UNIT_LIKE = re.compile(r"(?:[a-zµμ]*g|ml|iu|ui|%)")
_ATTACHED_AMOUNT = re.compile(rf"{_AMOUNT_LIKE}(?:[a-zµμ]*g|ml|iu|ui|%)")
_ANCHOR_PUNCTUATION = string.punctuation.replace("%", "") + "“”‘’…"


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    start: int
    end: int


def normalize_clean(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("OCR text must be a string")
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def normalize_key(text: str) -> str:
    """Keep symbols and name digits; only fold accents and whitespace."""
    decomposed = unicodedata.normalize("NFD", normalize_clean(text).translate(_DIACRITICS))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _number(value: str) -> str | None:
    if _GROUPING.fullmatch(value) or Decimal(value.replace(",", ".")) <= 0:
        return None
    canonical = format(Decimal(value.replace(",", ".")), "f")
    return canonical.rstrip("0").rstrip(".") if "." in canonical else canonical


def _parse_strength(value: str) -> tuple[str, tuple[str, ...]] | None:
    if match := _CONCENTRATION.fullmatch(value):
        numerator = _number(match[1])
        denominator = _number(match[2]) if match[2] is not None else None
        if numerator is None or (match[2] is not None and denominator is None):
            return None
        suffix = "ml" if denominator is None else f"{denominator} ml"
        result = f"{numerator} mg/{suffix}"
        return result, (result,)
    if _COMBINATION.fullmatch(value):
        numbers = [_number(match[1]) for match in _MG_PART.finditer(value)]
        if any(number is None for number in numbers):
            return None
        parts = tuple(f"{number} mg" for number in numbers)
        return " + ".join(parts), parts
    if match := _SIMPLE.fullmatch(value):
        number = _number(match[1])
        if number is not None:
            result = f"{number} {match[2]}"
            return result, (result,)
    return None


def _anchor_text(token: _Token) -> str:
    # Punctuation can make an amount invalid, but cannot hide it from competing-group
    # detection. Only this signal is stripped: parsing still receives the original span.
    return token.value.strip(_ANCHOR_PUNCTUATION)


def _groups(tokens: list[_Token]) -> list[tuple[int, int]]:
    """Find whole connected expressions around amount/unit anchors, including invalid tails."""
    anchors = []
    for index, token in enumerate(tokens):
        if _ATTACHED_AMOUNT.fullmatch(_anchor_text(token)):
            anchors.append((index, index + 1))
        elif (
            _UNIT_LIKE.fullmatch(_anchor_text(token))
            and index > 0
            and _NUMBER_LIKE.fullmatch(_anchor_text(tokens[index - 1]))
        ):
            anchors.append((index - 1, index + 1))
        elif (
            _UNIT_LIKE.fullmatch(_anchor_text(token))
            and index > 1
            and tokens[index - 1].value in {"/", "+"}
            and _NUMBER_LIKE.fullmatch(_anchor_text(tokens[index - 2]))
        ):
            # Missing numerator units (5/ml) are a signal, never a supported format.
            anchors.append((index - 2, index + 1))

    expanded = []
    for start, end in anchors:
        # One expansion already covers the other amount anchors of a long mixture.
        # Do not walk the same connected token chain once for each component.
        if expanded and expanded[-1][0] <= start and end <= expanded[-1][1]:
            continue
        # A separated minus is still a sign, never harmless packaging punctuation.
        if start > 0 and tokens[start - 1].value in {"-", "−", "﹣", "－"}:
            start -= 1
        # Slashes and plus signs bind their operands. Keep even malformed operands so a
        # valid numerator or the first component cannot be extracted on its own.
        while start > 0 and tokens[start - 1].value in {"/", "+"}:
            start -= 1
            if start > 0:
                start -= 1
                if (
                    _UNIT_LIKE.fullmatch(_anchor_text(tokens[start]))
                    and start > 0
                    and _NUMBER_LIKE.fullmatch(_anchor_text(tokens[start - 1]))
                ):
                    start -= 1
        while end < len(tokens) and tokens[end].value in {"/", "+"}:
            end += 1
            if end < len(tokens):
                end += 1
                if (
                    _NUMBER_LIKE.fullmatch(_anchor_text(tokens[end - 1]))
                    and end < len(tokens)
                    and _UNIT_LIKE.fullmatch(_anchor_text(tokens[end]))
                ):
                    end += 1
        expanded.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(expanded):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


_FILTERS = (
    ("registration", re.compile(r"(?<![\w-])(?:(?:sdk)\s*:?\s*)?(?:vd|vn)-[0-9]+-[0-9]+(?![\w-])")),
    ("packaging", re.compile(r"\bhop\s+[0-9]+\s+vi\b|\b[0-9]+\s+vien\b")),
    ("dosage_form", re.compile(r"\b(?:vien nen|vien sui|sui|siro)\b")),
    ("symbol", re.compile(r"[®™•]")),
)


def _eligibility(name: str, key: str) -> tuple[bool, str]:
    if not name or not any(c.isalnum() for c in name):
        return False, "empty_or_filtered" if key else "empty"
    if re.fullmatch(r"[a-z]+\.", name):
        return False, "truncated_token"
    if re.search(r"[a-z]{4,}", name):
        return True, "informative_token"
    return False, "insufficient_context"


def _line(raw: str, line_id: int, offset: int, ending: str) -> OcrLine:
    clean = normalize_clean(raw)
    key = normalize_key(clean)
    tokens = [_Token(m[0], m.start(), m.end()) for m in _TOKENS.finditer(key)]
    strengths, unknown, removed = [], [], []
    for start, end in _groups(tokens):
        first, last = tokens[start].start, tokens[end - 1].end
        source = key[first:last]
        parsed = _parse_strength(source)
        occurrence = StrengthOccurrence(
            line_id,
            source,
            first,
            last,
            parsed[0] if parsed else None,
            parsed[1] if parsed else (),
            StrengthStatus.PARSED if parsed else StrengthStatus.UNPARSED,
            None if parsed else "unsupported_or_invalid_expression",
        )
        if parsed:
            strengths.append(occurrence)
            removed.append(RemovedSpan(first, last, source, "strength"))
        else:
            unknown.append(occurrence)
    # Keep coordinates in the pre-filter key. Replacing with spaces avoids accidental
    # concatenation and prevents filters from spanning already-extracted expressions.
    working = list(key)
    for span in removed:
        working[span.start : span.end] = " " * (span.end - span.start)
    for reason, pattern in _FILTERS:
        for match in pattern.finditer("".join(working)):
            removed.append(
                RemovedSpan(match.start(), match.end(), key[match.start() : match.end()], reason)
            )
            working[match.start() : match.end()] = " " * (match.end() - match.start())
    name = " ".join("".join(working).split())
    eligible, reason = _eligibility(name, key)
    return OcrLine(
        line_id,
        raw,
        offset,
        offset + len(raw),
        ending,
        clean,
        key,
        name,
        tuple(strengths),
        tuple(unknown),
        tuple(sorted(removed, key=lambda s: s.start)),
        eligible,
        reason,
    )


def normalize_ocr_text(text: str) -> NormalizedOcrText:
    """Preserve each source line; syntax recognition never verifies a medicine."""
    if not isinstance(text, str):
        raise TypeError("OCR text must be a string")
    if not text:
        return NormalizedOcrText(text)
    lines = []
    offset = 0
    for match in re.finditer(r"\r\n|\r|\n", text):
        lines.append(_line(text[offset : match.start()], len(lines) + 1, offset, match[0]))
        offset = match.end()
    lines.append(_line(text[offset:], len(lines) + 1, offset, ""))
    frozen = tuple(lines)
    return NormalizedOcrText(text, frozen, cluster_ocr_lines(frozen), summarize_strengths(frozen))
