from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# The comparison operators of an expert rule condition, and whether each includes its bound.
LOWER_OPERATORS = {"greater_than": False, "greater_than_or_equal": True}
UPPER_OPERATORS = {"less_than": False, "less_than_or_equal": True}
OPERATOR_WORDS = {
    "equals": "=", "not_equals": "≠", "greater_than": ">", "greater_than_or_equal": "≥", "less_than": "<",
    "less_than_or_equal": "≤", "in": "thuộc", "not_in": "không thuộc", "contains": "chứa",
    "not_contains": "không chứa", "is_null": "để trống", "is_not_null": "có giá trị",
}
NULL = ("null", None)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass(frozen=True)
class Bound:
    value: float
    inclusive: bool

    def text(self, lower: bool) -> str:
        symbol = ("≥" if self.inclusive else ">") if lower else ("≤" if self.inclusive else "<")
        return f"{symbol} {format_number(self.value)}"


def _tighter(first: Bound | None, second: Bound | None, lower: bool) -> Bound | None:
    if first is None or second is None:
        return first or second
    if first.value != second.value:
        return first if (first.value > second.value) == lower else second
    # At the same value, the bound that leaves the value out is the tighter one.
    return first if not first.inclusive else second


@dataclass(frozen=True)
class Interval:
    lower: Bound | None = None
    upper: Bound | None = None

    def intersect(self, other: "Interval") -> "Interval":
        return Interval(_tighter(self.lower, other.lower, True), _tighter(self.upper, other.upper, False))

    def is_empty(self) -> bool:
        if self.lower is None or self.upper is None:
            return False
        if self.lower.value != self.upper.value:
            return self.lower.value > self.upper.value
        return not (self.lower.inclusive and self.upper.inclusive)

    def is_unbounded(self) -> bool:
        return self.lower is None and self.upper is None

    def admits(self, value: float) -> bool:
        return not self.intersect(Interval(Bound(value, True), Bound(value, True))).is_empty()

    def contains(self, other: "Interval") -> bool:
        return other.is_empty() or self.intersect(other) == other


def member(value: Any) -> tuple[str, Any]:
    if value is None:
        return NULL
    if isinstance(value, bool):
        return ("boolean", value)
    if is_number(value):
        return ("number", float(value))
    return ("text", " ".join(str(value).split()))


def _member_text(item: tuple[str, Any]) -> str:
    kind, value = item
    if kind == "number":
        return format_number(value)
    if kind == "boolean":
        return "đúng" if value else "sai"
    return "trống" if kind == "null" else f"“{value}”"


def _sort_key(item: tuple[str, Any]) -> tuple[str, str]:
    return item[0], format_number(item[1]) if item[0] == "number" else str(item[1])


@dataclass(frozen=True)
class ColumnDomain:
    interval: Interval = field(default_factory=Interval)
    members: frozenset | None = None
    excluded: frozenset = frozenset()

    def admits(self, item: tuple[str, Any]) -> bool:
        if self.members is not None:
            return item in self.members
        if item in self.excluded:
            return False
        return item[0] != "number" or self.interval.admits(item[1])

    def constrain(self, operator: str, value: Any) -> "ColumnDomain":
        interval, members, excluded = self.interval, self.members, self.excluded
        if operator in LOWER_OPERATORS or operator in UPPER_OPERATORS:
            if not is_number(value):
                return self
            if operator in LOWER_OPERATORS:
                interval = interval.intersect(Interval(lower=Bound(float(value), LOWER_OPERATORS[operator])))
            else:
                interval = interval.intersect(Interval(upper=Bound(float(value), UPPER_OPERATORS[operator])))
        elif operator in ("equals", "in"):
            values = value if operator == "in" else [value]
            if not isinstance(values, list):
                return self
            allowed = frozenset(member(item) for item in values)
            members = allowed if members is None else members & allowed
        elif operator in ("not_equals", "not_in"):
            values = value if operator == "not_in" else [value]
            if not isinstance(values, list):
                return self
            excluded = excluded | {member(item) for item in values}
        elif operator == "is_null":
            members = frozenset({NULL}) if members is None else members & {NULL}
        elif operator == "is_not_null":
            excluded = excluded | {NULL}
        else:
            return self
        return _domain(interval, members, excluded)

    def is_empty(self) -> bool:
        return self.members == frozenset() or (self.members is None and self.interval.is_empty())

    def is_threshold(self) -> bool:
        return self.members is None and not self.interval.is_unbounded()

    def overlaps(self, other: "ColumnDomain") -> bool:
        if self.is_empty() or other.is_empty():
            return False
        if self.members is not None:
            return any(other.admits(item) for item in self.members)
        if other.members is not None:
            return any(self.admits(item) for item in other.members)
        common = self.interval.intersect(other.interval)
        if common.is_empty():
            return False
        if common.lower is None or common.upper is None or common.lower.value != common.upper.value:
            return True
        # A single shared number may still be excluded by either side, such as `>= 50` against `<= 50` and `!= 50`.
        point = ("number", common.lower.value)
        return self.admits(point) and other.admits(point)

    def contains(self, other: "ColumnDomain") -> bool:
        if other.is_empty():
            return True
        if other.members is not None:
            return all(self.admits(item) for item in other.members)
        if self.members is not None:
            return False
        return self.interval.contains(other.interval) and not any(other.admits(item) for item in self.excluded)

    def describe(self, label: str) -> str:
        if self.members is not None:
            values = sorted(self.members, key=_sort_key)
            if not values:
                return f"{label}: không có giá trị nào"
            if values == [NULL]:
                return f"{label} để trống"
            if len(values) == 1:
                return f"{label} = {_member_text(values[0])}"
            return f"{label} thuộc {{{', '.join(_member_text(item) for item in values)}}}"
        parts = []
        lower, upper = self.interval.lower, self.interval.upper
        if lower and upper and lower.value == upper.value and lower.inclusive and upper.inclusive:
            parts.append(f"= {format_number(lower.value)}")
        else:
            parts.extend(bound.text(is_lower) for bound, is_lower in ((lower, True), (upper, False)) if bound)
        others = sorted((item for item in self.excluded if item != NULL), key=_sort_key)
        if len(others) == 1:
            parts.append(f"≠ {_member_text(others[0])}")
        elif others:
            parts.append(f"không thuộc {{{', '.join(_member_text(item) for item in others)}}}")
        if NULL in self.excluded:
            parts.append("có giá trị")
        return f"{label} {' và '.join(parts)}" if parts else f"{label}: mọi giá trị"


def _domain(interval: Interval, members: frozenset | None, excluded: frozenset) -> ColumnDomain:
    if members is None:
        return ColumnDomain(interval, None, frozenset(excluded))
    allowed = ColumnDomain(interval, None, frozenset(excluded))
    return ColumnDomain(Interval(), frozenset(item for item in members if allowed.admits(item)), frozenset())


UNCONSTRAINED = ColumnDomain()


def rule_domains(conditions: Iterable[dict[str, Any]]) -> dict[int, ColumnDomain]:
    domains: dict[int, ColumnDomain] = {}
    for condition in conditions:
        column_id = condition["field_ref"]["column_dictionary_id"]
        domain = domains.get(column_id, UNCONSTRAINED).constrain(condition["operator"], condition.get("value"))
        domains[column_id] = domain
    return {column_id: domain for column_id, domain in domains.items() if domain != UNCONSTRAINED}


def regions_overlap(first: dict[int, ColumnDomain], second: dict[int, ColumnDomain]) -> bool:
    columns = first.keys() | second.keys()
    return all(first.get(column, UNCONSTRAINED).overlaps(second.get(column, UNCONSTRAINED)) for column in columns)


def region_contains(outer: dict[int, ColumnDomain], inner: dict[int, ColumnDomain]) -> bool:
    columns = outer.keys() | inner.keys()
    return all(outer.get(column, UNCONSTRAINED).contains(inner.get(column, UNCONSTRAINED)) for column in columns)


def condition_phrase(condition: dict[str, Any], label: str) -> str:
    operator = condition["operator"]
    words = OPERATOR_WORDS.get(operator, operator)
    if operator in ("is_null", "is_not_null"):
        return f"{label} {words}"
    value = condition.get("value")
    values = value if isinstance(value, list) else [value]
    shown = ", ".join(_member_text(member(item)) for item in values)
    return f"{label} {words} {{{shown}}}" if isinstance(value, list) else f"{label} {words} {shown}"


def bound_differences(stated: Interval, actual: Interval) -> list[str]:
    differences = []
    for lower, stated_bound, actual_bound in ((True, stated.lower, actual.lower), (False, stated.upper, actual.upper)):
        if stated_bound is not None and stated_bound != actual_bound:
            side = "dưới" if lower else "trên"
            actual_text = actual_bound.text(lower) if actual_bound else "không có"
            differences.append(f"ngưỡng {side} {stated_bound.text(lower)} so với {actual_text}")
    return differences
