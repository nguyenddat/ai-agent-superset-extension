import re
import unicodedata

from .srv_contradiction_conditions import Bound, Interval

_NUMBER = r"(?P<{name}>-?\d+(?:[.,]\d+)?)"
# A short unit right after a number: °C, mm, km/h, %; a count word there means the number is not a threshold.
_UNIT = r"(?:\s*(?P<unit>[^\s\d;,()]{1,6}))?"
_COUNT_WORDS = ("ngày", "tháng", "năm", "tuần", "lần")
_START = r"(?<!\w)"


def _phrase(pattern: str) -> re.Pattern:
    expanded = pattern.replace("{N}", _NUMBER.format(name="value")).replace("{M}", _NUMBER.format(name="upper"))
    return re.compile(_START + expanded.replace("{U}", _UNIT))


# Each phrase and the side it bounds: `lower`/`upper` with whether the number is included, or `range`.
_PHRASES = (
    (_phrase(r"từ\s+{N}{U}\s+trở\s+(?:lên|đi)"), "lower", True),
    (_phrase(r"từ\s+{N}{U}\s+trở\s+xuống"), "upper", True),
    (_phrase(r"(?:từ|trong khoảng|khoảng)\s+{N}(?:\s*[^\s\d;,()]{1,6})?\s*(?:đến|tới|-|–)\s*{M}{U}"), "range", True),
    (
        _phrase(
            r"(?:(?:lớn|cao|nhiều) hơn hoặc bằng|không (?:dưới|thấp hơn|ít hơn|nhỏ hơn)|ít nhất|tối thiểu|>=|≥|=>)"
            r"\s*{N}{U}"
        ),
        "lower",
        True,
    ),
    (
        _phrase(
            r"(?:(?:nhỏ|thấp|ít) hơn hoặc bằng|không (?:quá|vượt quá|trên|cao hơn|lớn hơn|nhiều hơn)|tối đa|nhiều nhất"
            r"|<=|≤|=<)\s*{N}{U}"
        ),
        "upper",
        True,
    ),
    (_phrase(r"(?:trên|lớn hơn|cao hơn|nhiều hơn|vượt quá|vượt|>)\s*{N}{U}"), "lower", False),
    (_phrase(r"(?:dưới|nhỏ hơn|thấp hơn|ít hơn|<)\s*{N}{U}"), "upper", False),
)


def main_clause(text: str) -> str:
    """The first clause of a text, up to a semicolon or the end of a sentence.

    A definition states its own threshold first and may name a stronger grade after it, as in "trên 50 mm; trên 100 mm
    là mưa rất to", so only the first clause is read.
    """
    # A dot ends a sentence only before a space or the end, so a decimal such as 1.5 stays whole.
    return " ".join(re.split(r";|\n|\.(?:\s|$)", text, maxsplit=1)[0].split())


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def threshold_phrases(text: str) -> list[tuple[int, Interval]]:
    """Every threshold phrase of a text with where it starts, read left to right without overlaps."""
    normalized = unicodedata.normalize("NFC", text).casefold()
    matches = []
    for pattern, side, inclusive in _PHRASES:
        for match in pattern.finditer(normalized):
            unit = match.group("unit") or ""
            if unit.startswith(_COUNT_WORDS):
                continue
            value = _number(match.group("value"))
            if side == "range":
                interval = Interval(Bound(value, True), Bound(_number(match.group("upper")), True))
            elif side == "lower":
                interval = Interval(lower=Bound(value, inclusive))
            else:
                interval = Interval(upper=Bound(value, inclusive))
            matches.append((match.start(), match.end(), interval))
    # The earliest phrase wins, and the longest among those starting together: "không quá 5" over "quá 5".
    matches.sort(key=lambda item: (item[0], -item[1]))
    chosen, reached = [], -1
    for start, end, interval in matches:
        if start >= reached:
            chosen.append((start, interval))
            reached = end
    return chosen


def stated_interval(text: str | None) -> Interval | None:
    """The numeric range the first clause of a text states, such as > 50 for "Ngày có tổng lượng mưa trên 50 mm".

    None when the clause states no threshold, or thresholds that cannot hold together.
    """
    if not text:
        return None
    phrases = threshold_phrases(main_clause(text))
    if not phrases:
        return None
    interval = Interval()
    for _, phrase in phrases:
        interval = interval.intersect(phrase)
    return None if interval.is_empty() else interval
