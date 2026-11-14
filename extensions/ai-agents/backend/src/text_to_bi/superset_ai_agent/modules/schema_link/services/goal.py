from dataclasses import dataclass, field
from typing import Any

from ...chat.services.query import OPERATORS
from ..exceptions import GoalError
from .graph import SchemaGraph

AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT")
TIME_GRAINS = ("hour", "day", "week", "month", "quarter", "year")
# From finest to coarsest; a query may group a kind of row at its own grain or coarser, and `instant` rows at any.
GRAIN_ORDER = ("instant", "hour", "day", "week", "month", "quarter", "year")
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10_000


@dataclass
class Measure:
    table: int
    column: str | None
    aggregation: str
    label: str
    source: str


@dataclass
class GroupBy:
    table: int
    column: str
    label: str
    time_grain: str | None = None


@dataclass
class Filter:
    table: int
    column: str
    operator: str
    value: Any
    label: str
    source: str = "mục tiêu"


@dataclass
class RowKind:
    table: int
    column: str
    value: str
    label: str
    grain: str


@dataclass
class Goal:
    measures: list[Measure]
    group_by: list[GroupBy] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    row_kinds: list[RowKind] = field(default_factory=list)
    limit: int = DEFAULT_LIMIT

    @property
    def root(self) -> int:
        return self.measures[0].table

    @property
    def terminals(self) -> list[int]:
        tables = [self.root, *(item.table for item in self.group_by), *(item.table for item in self.filters)]
        tables += [item.table for item in self.row_kinds]
        return list(dict.fromkeys(tables))


def _table(graph: SchemaGraph, raw: dict[str, Any], what: str) -> int:
    table = raw.get("dataset_id")
    if table not in graph.tables:
        raise GoalError(f"{what}: bảng {table!r} không có trong đồ thị (chỉ base table bạn được xem).")
    return table


def _column(graph: SchemaGraph, table: int, name: Any, what: str) -> dict[str, Any]:
    column = graph.column(table, name) if isinstance(name, str) else None
    if column is None:
        raise GoalError(f"{what}: cột {name!r} không có ở bảng {graph.table_name(table)}.")
    return column


def _measure(graph: SchemaGraph, raw: dict[str, Any]) -> Measure:
    table = _table(graph, raw, "Đo")
    aggregation = raw.get("aggregation")
    if aggregation not in AGGREGATIONS:
        raise GoalError(f"Đo: phép gộp {aggregation!r} không hợp lệ.")
    if raw.get("column") is None:
        if aggregation != "COUNT":
            raise GoalError("Đo: không có cột thì chỉ đếm số dòng (COUNT).")
        return Measure(table, None, "COUNT", raw.get("label") or f"Số dòng {graph.table_name(table)}", "đếm dòng")
    column = _column(graph, table, raw["column"], "Đo")
    allowed = column.get("aggregations") or []
    if aggregation not in ("COUNT", "COUNT_DISTINCT"):
        if column.get("role") != "measure":
            raise GoalError(f"Đo: cột {column['name']} không phải cột đo lường, chỉ đếm được.")
        if allowed and aggregation not in allowed:
            raise GoalError(f"Đo: {column['name']} chỉ gộp được bằng {', '.join(allowed)}.")
    return Measure(table, column["name"], aggregation, raw.get("label") or column["label"], "cột đo lường")


def resolve_goal(raw: dict[str, Any], graph: SchemaGraph) -> Goal:
    """The goal with every table and column checked against the graph. Raises GoalError."""
    if not isinstance(raw, dict) or not isinstance(raw.get("measures"), list) or not raw["measures"]:
        raise GoalError("Mục tiêu cần ít nhất một phép đo (measures).")
    measures, filters = [], []
    for item in raw["measures"]:
        if not isinstance(item, dict):
            raise GoalError("Mỗi phép đo phải là một object.")
        measures.append(_measure(graph, item))
    if len({measure.table for measure in measures}) > 1:
        raise GoalError("Các phép đo phải nằm trên cùng một bảng gốc; tách thành nhiều câu hỏi.")

    group_by = []
    for item in raw.get("group_by") or []:
        table = _table(graph, item, "Chia theo")
        column = _column(graph, table, item.get("column"), "Chia theo")
        grain = item.get("time_grain")
        if grain is not None and (grain not in TIME_GRAINS or not column.get("temporal_kind")):
            raise GoalError(f"Chia theo: {column['name']} không gom theo {grain!r} được.")
        group_by.append(GroupBy(table, column["name"], item.get("label") or column["label"], grain))

    for item in raw.get("filters") or []:
        table = _table(graph, item, "Lọc")
        column = _column(graph, table, item.get("column"), "Lọc")
        operator, value = item.get("operator"), item.get("value")
        if operator not in OPERATORS or value is None or (operator in ("IN", "NOT IN")) != isinstance(value, list):
            raise GoalError(f"Lọc {column['name']}: toán tử hoặc giá trị không hợp lệ.")
        label = item.get("label") or f"{column['label']} {operator} {value}"
        filters.append(Filter(table, column["name"], operator, value, label))

    row_kinds = []
    for item in raw.get("row_kinds") or []:
        table = _table(graph, item, "Loại dòng")
        time = graph.tables[table].get("time") or {}
        kind = next((kind for kind in time.get("row_kinds", []) if kind["value"] == item.get("value")), None)
        if not time.get("row_kind_column") or kind is None:
            raise GoalError(f"Loại dòng {item.get('value')!r} không có ở bảng {graph.table_name(table)}.")
        label = kind.get("label") or kind["value"]
        row_kinds.append(RowKind(table, time["row_kind_column"], kind["value"], label, kind["grain"]))

    limit = raw.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise GoalError(f"limit phải từ 1 đến {MAX_LIMIT}.")
    return Goal(measures, group_by, filters, row_kinds, limit)


def grain_problems(goal: Goal, tables: list[int], graph: SchemaGraph) -> list[dict[str, Any]]:
    """Tables in the join that mix grains without a chosen kind of row, or group finer than the chosen kind's grain."""
    chosen = {item.table: item for item in goal.row_kinds}
    problems = []
    for table in tables:
        kinds = (graph.tables[table].get("time") or {}).get("row_kinds", [])
        if len(kinds) > 1 and table not in chosen:
            problems.append({
                "table": table, "kind": "row_kind_missing",
                "message": f"{graph.table_name(table)} trộn nhiều loại dòng; chọn một: "
                           + ", ".join(f"{kind['value']} ({kind['grain']})" for kind in kinds),
                "options": [kind["value"] for kind in kinds],
            })
    for item in goal.group_by:
        row_kind = chosen.get(item.table)
        if item.time_grain and row_kind and row_kind.grain != "instant" and (
            GRAIN_ORDER.index(item.time_grain) < GRAIN_ORDER.index(row_kind.grain)
        ):
            problems.append({
                "table": item.table, "kind": "grain_too_fine",
                "message": f"{row_kind.label} có grain {row_kind.grain}, không chia theo {item.time_grain} được.",
                "options": [],
            })
    return problems
