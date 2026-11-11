import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ....common.utils.type_formatter import canonical_json
from ..exceptions import ApprovedMetricContractRequiredError, MetricContractValidationError
from .query_defaults import (
    MetricQueryDefaults,
    applied_query_defaults,
    checked_query_filter,
    query_column,
    time_axis_column,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AGGREGATES = (exp.Avg, exp.Count, exp.Max, exp.Min, exp.Sum)
# Every node a contract metric may contain. Anything else, such as a subquery, another function, DISTINCT, FILTER or
# a window, makes the metric ineligible.
_CONTRACT_METRIC_NODES = (
    *_AGGREGATES,
    exp.Case,
    exp.If,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Paren,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.In,
    exp.Is,
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Neg,
)
# A ratio divides two contract aggregates; only these nodes may join them.
_RATIO_NODES = (exp.Div, exp.Mul, exp.Nullif)
METRIC_CONTRACT_RULE = (
    "Công thức phải là đúng một AVG, COUNT, MAX, MIN hoặc SUM trên cột của dataset, có thể ở dạng "
    "CASE WHEN <so sánh cột với hằng số> THEN <cột hoặc số> END; hoặc tỷ lệ giữa hai hàm như vậy, viết "
    "<hệ số thập phân> * AGG(...) / NULLIF(AGG(...), 0), ví dụ 100.0 * ... cho phần trăm."
)
MAX_DIMENSIONS = 50
MAX_FILTERS = 50


@dataclass(frozen=True)
class ContractMetricTerm:
    """One aggregate of a contract formula: what it aggregates and which rows it counts."""

    aggregation: str
    measure_column: str | None
    measure_constant: str | None
    condition: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation,
            "measure_column": self.measure_column,
            "measure_constant": self.measure_constant,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class ContractMetricFormula:
    """The parts of a metric formula that contracts accept, for review and for binding to live columns.

    A plain metric is its numerator alone; a ratio also has a denominator and the decimal scale that multiplies it.
    """

    numerator: ContractMetricTerm
    denominator: ContractMetricTerm | None
    scale: str | None
    columns: frozenset[str]

    @property
    def measure_column(self) -> str | None:
        return self.numerator.measure_column

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.numerator.as_dict(),
            "denominator": self.denominator.as_dict() if self.denominator else None,
            "scale": self.scale,
            "columns": sorted(self.columns),
        }


def _unwrapped(node: Any) -> Any:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _contract_term(node: Any) -> ContractMetricTerm | None:
    """``AGG(column)`` or ``AGG(CASE WHEN condition THEN column-or-number END)``; None for anything else."""
    if not isinstance(node, _AGGREGATES):
        return None
    inner = [child for child in node.walk() if child is not node]
    if any(not isinstance(child, _CONTRACT_METRIC_NODES) or isinstance(child, _AGGREGATES) for child in inner):
        return None
    measure = node.this
    condition = None
    if isinstance(measure, exp.Case):
        branches = measure.args.get("ifs") or []
        default = measure.args.get("default")
        if len(branches) != 1 or not (default is None or isinstance(default, exp.Null)):
            return None
        condition = branches[0].this.sql(dialect="postgres")
        measure = branches[0].args.get("true")
        if not isinstance(measure, (exp.Column, exp.Literal, exp.Neg)):
            return None
    elif not isinstance(measure, exp.Column):
        return None
    return ContractMetricTerm(
        aggregation=node.key.upper(),
        measure_column=measure.name if isinstance(measure, exp.Column) else None,
        measure_constant=None if isinstance(measure, exp.Column) else measure.sql(dialect="postgres"),
        condition=condition,
    )


def _decimal_scale(node: Any) -> str | None:
    """A positive number written with a decimal point, such as 100.0, so the division is not an integer one."""
    if isinstance(node, exp.Literal) and node.is_number and "." in node.this:
        try:
            return node.this if float(node.this) > 0 else None
        except ValueError:
            return None
    return None


def _ratio(tree: Any) -> tuple[ContractMetricTerm, ContractMetricTerm, str] | None:
    """``scale * AGG(...) / NULLIF(AGG(...), 0)``, the scale on either side of the numerator."""
    if not isinstance(tree, exp.Div):
        return None
    scaled, guarded = _unwrapped(tree.this), _unwrapped(tree.expression)
    if not isinstance(scaled, exp.Mul) or not isinstance(guarded, exp.Nullif):
        return None
    left, right = _unwrapped(scaled.this), _unwrapped(scaled.expression)
    scale, aggregate = _decimal_scale(left), right
    if scale is None:
        scale, aggregate = _decimal_scale(right), left
    zero = _unwrapped(guarded.expression)
    if scale is None or not (isinstance(zero, exp.Literal) and zero.is_number and float(zero.this) == 0):
        return None
    numerator, denominator = _contract_term(aggregate), _contract_term(_unwrapped(guarded.this))
    return (numerator, denominator, scale) if numerator and denominator else None


def parse_contract_metric(expression: str) -> ContractMetricFormula | None:
    """Parse one contract aggregate, or a ratio of two; None for any other formula.

    A condition may only compare unqualified columns with constants. A ratio needs a decimal scale, because
    COUNT / COUNT is an integer division in PostgreSQL, and NULLIF around its denominator, so no row divides by zero.
    """
    try:
        tree = _unwrapped(sqlglot.parse_one(expression))
    except SqlglotError:
        return None
    nodes = list(tree.walk())
    if any(not isinstance(node, (*_CONTRACT_METRIC_NODES, *_RATIO_NODES)) for node in nodes):
        return None
    columns = list(tree.find_all(exp.Column))
    if not columns or any(column.table for column in columns):
        return None
    column_names = frozenset(column.name for column in columns)
    if term := _contract_term(tree):
        return ContractMetricFormula(numerator=term, denominator=None, scale=None, columns=column_names)
    if ratio := _ratio(tree):
        numerator, denominator, scale = ratio
        return ContractMetricFormula(numerator=numerator, denominator=denominator, scale=scale, columns=column_names)
    return None


def _live_columns(dataset: Any) -> dict[Any, Any]:
    return {getattr(column, "column_name", None): column for column in getattr(dataset, "columns", [])}


def _metric_column(dataset: Any, metric: Any) -> Any | None:
    """The live column a contract metric measures, or None for a constant measure or an ineligible formula."""
    formula = parse_contract_metric(str(getattr(metric, "expression", "") or ""))
    return _live_columns(dataset).get(formula.measure_column) if formula and formula.measure_column else None


def metric_contract_ineligibility(dataset: Any, metric: Any) -> str | None:
    """Why a metric cannot have a contract, or None when it can.

    Superset's ``TableColumn`` does not expose sensitivity metadata.  This layer
    therefore does not invent a non-authoritative ``is_sensitive`` flag; any
    sensitivity policy must be enforced by Superset datasource/RLS permissions.

    A virtual dataset is eligible: its SQL is part of the contract hash, so editing it voids an approval.
    """
    metric_name = getattr(metric, "metric_name", None)
    if not isinstance(metric_name, str) or not _IDENTIFIER.fullmatch(metric_name):
        return "Tên metric chỉ được gồm chữ cái không dấu, chữ số và dấu gạch dưới."
    formula = parse_contract_metric(str(getattr(metric, "expression", "") or ""))
    if formula is None:
        return METRIC_CONTRACT_RULE
    live_columns = _live_columns(dataset)
    for column_name in sorted(formula.columns):
        column = live_columns.get(column_name)
        if column is None:
            return f"Cột {column_name} không có trong dataset."
        if getattr(column, "is_active", None) is not True:
            return f"Cột {column_name} đang bị tắt (không active)."
        if getattr(column, "expression", None):
            return f"Cột {column_name} là cột tính toán."
    return None


def metric_is_eligible_for_contract(dataset: Any, metric: Any) -> bool:
    return metric_contract_ineligibility(dataset, metric) is None


def _safe_connection_identity(database: Any) -> dict[str, Any]:
    """Return a stable connection identity without putting credentials in the hash input."""
    return {
        "id": getattr(database, "id", None),
        "name": getattr(database, "database_name", None),
        "uuid": getattr(database, "uuid", None),
        "backend": getattr(database, "backend", None),
    }


# Relationship contracts use the same deliberately credential-free connection identity.
safe_connection_identity = _safe_connection_identity


def metric_contract_hash(dataset: Any, metric: Any, defaults: Any = None) -> str:
    """Hash the live identity of a saved metric, including its datasource location.

    The JSON encoding deliberately distinguishes a physical table from a virtual
    dataset SQL definition.  Approval is invalid as soon as any of these values
    changes.

    ``defaults`` are the metric's grain, time anchor and default filters (``MetricQueryDefaults``). They are part of
    what the metric means, so changing them voids an approval as a formula edit does; a metric without any keeps the
    hash it had before they existed.
    """
    database = getattr(dataset, "database", None)
    metric_column = _metric_column(dataset, metric)
    payload = {
        "dataset_id": getattr(dataset, "id", None),
        "metric_id": getattr(metric, "id", None),
        "metric_name": str(getattr(metric, "metric_name", "")),
        "expression": str(getattr(metric, "expression", "")),
        "catalog": getattr(dataset, "catalog", None),
        "schema": getattr(dataset, "schema", None),
        "table": getattr(dataset, "table_name", None),
        "sql": getattr(dataset, "sql", None),
        "datasource_type": "virtual" if getattr(dataset, "sql", None) else "physical",
        "database": _safe_connection_identity(database),
        "metric_column_expression": getattr(metric_column, "expression", None),
    }
    if defaults is not None and not defaults.is_empty():
        payload["query_defaults"] = defaults.as_dict()
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def contract_is_approved_current(contract: Any, dataset: Any, metric: Any, defaults: Any = None) -> bool:
    """Return true only for an approved record bound to this live dataset/metric and its query defaults."""
    return bool(
        contract
        and getattr(contract, "status", None) == "approved"
        and getattr(contract, "dataset_id", None) == getattr(dataset, "id", None)
        and getattr(contract, "metric_id", None) == getattr(metric, "id", None)
        and metric_is_eligible_for_contract(dataset, metric)
        and getattr(contract, "expression_hash", None) == metric_contract_hash(dataset, metric, defaults)
    )


def metric_contract_state(contract: Any, dataset: Any, metric: Any, defaults: Any = None) -> str:
    """The review state an administrator sees for a metric.

    ``outdated`` is a candidate or approval whose metric changed after it was recorded, so it can be neither
    approved nor executed until a new candidate is created.
    """
    eligible = metric_is_eligible_for_contract(dataset, metric)
    status = getattr(contract, "status", None)
    if contract is None:
        return "not_started" if eligible else "ineligible"
    if status == "revoked":
        return "revoked"
    if status == "approved":
        return "approved" if contract_is_approved_current(contract, dataset, metric, defaults) else "outdated"
    current_hash = metric_contract_hash(dataset, metric, defaults)
    unchanged = eligible and getattr(contract, "expression_hash", None) == current_hash
    return "candidate" if unchanged else "outdated"


def planned_metric_chart(
    dataset: Any,
    metric: Any,
    query: Any,
    max_rows: int,
    defaults: MetricQueryDefaults | None = None,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Make the only ChartData payload accepted by metric execution, and say which of the metric's defaults it applied.

    This admits names from live TableColumn metadata only; it intentionally has no SQL, join, expression, arbitrary
    metric, or client-controlled row-limit escape hatch. Besides dimensions and filters a caller may send `time_grain`
    to group the metric's time column by another grain, and `apply_defaults: false` to skip the metric's defaults.
    """
    if isinstance(query, dict) and "joins" in query:
        raise MetricContractValidationError("Truy vấn metric không nối nhiều dataset.")
    if not isinstance(query, dict) or set(query) - {"dimensions", "filters", "time_grain", "apply_defaults"}:
        raise MetricContractValidationError(
            "Truy vấn chỉ gồm dimensions, filters, time_grain và apply_defaults."
        )
    dimensions = query.get("dimensions", [])
    filters = query.get("filters", [])
    if not isinstance(dimensions, list) or not isinstance(filters, list):
        raise MetricContractValidationError("dimensions và filters phải là mảng.")
    if len(dimensions) > MAX_DIMENSIONS or len(filters) > MAX_FILTERS:
        raise MetricContractValidationError(
            f"Truy vấn có tối đa {MAX_DIMENSIONS} chiều phân tích và {MAX_FILTERS} bộ lọc."
        )
    apply_defaults = query.get("apply_defaults", True)
    if not isinstance(apply_defaults, bool):
        raise MetricContractValidationError("apply_defaults phải là true hoặc false.")
    columns = {str(getattr(column, "column_name", "")): column for column in getattr(dataset, "columns", [])}
    selected = [query_column(columns, name, "groupby") for name in dimensions]
    if len(set(selected)) != len(selected):
        raise MetricContractValidationError("Mỗi chiều phân tích chỉ chọn một lần.")
    chart_filters = [checked_query_filter(columns, item) for item in filters]
    filtered_columns = {item["col"] for item in chart_filters}
    default_filters, time_grain, applied = applied_query_defaults(
        defaults, filtered_columns, selected, query.get("time_grain"), apply_defaults, latest_time, now
    )
    time_column = defaults.time_column if defaults else None
    chart_columns: list[Any] = [
        time_axis_column(name, time_grain) if time_grain and name == time_column else name for name in selected
    ]
    payload = {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [
            {
                "columns": chart_columns,
                "metrics": [metric.metric_name],
                "filters": chart_filters + default_filters,
                "row_limit": max_rows + 1,
            }
        ],
        "result_type": "full",
        "result_format": "json",
    }
    return payload, applied


def build_metric_chart_payload(
    dataset: Any, metric: Any, query: Any, max_rows: int, defaults: MetricQueryDefaults | None = None
) -> dict[str, Any]:
    """The ChartData payload of `planned_metric_chart`, without the account of the defaults it applied."""
    return planned_metric_chart(dataset, metric, query, max_rows, defaults)[0]


def execute_approved_chart_query(
    contract: Any,
    dataset: Any,
    metric: Any,
    query: Any,
    max_rows: int,
    runner: Any,
    allow_candidate: bool = False,
    defaults: MetricQueryDefaults | None = None,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> Any:
    """Gate the ChartData runner before it can validate or execute anything.

    ``allow_candidate`` lets a candidate whose metric is unchanged since it was proposed run: callers grant it to
    administrators, as a review preview, and to a candidate the AI Agent built, as a provisional figure. Any other
    metric runs only once approved. ``defaults`` are the metric's live query defaults: they are part of what was
    reviewed and are applied to the query, and the result then carries ``applied_defaults``.
    """
    previewable = (
        allow_candidate
        and contract is not None
        and metric_contract_state(contract, dataset, metric, defaults) == "candidate"
    )
    if not previewable and not contract_is_approved_current(contract, dataset, metric, defaults):
        raise ApprovedMetricContractRequiredError()
    payload, applied = planned_metric_chart(dataset, metric, query, max_rows, defaults, latest_time)
    result = runner(payload)
    if applied is not None and isinstance(result, dict):
        return {**result, "applied_defaults": applied}
    return result

