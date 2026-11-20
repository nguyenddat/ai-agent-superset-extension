from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

AGGREGATES = (exp.Avg, exp.Count, exp.Max, exp.Min, exp.Sum)
# Every node a contract formula may contain; a subquery, another function, DISTINCT, FILTER or a window rules it out.
CONTRACT_METRIC_NODES = (
    *AGGREGATES,
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
RATIO_NODES = (exp.Div, exp.Mul, exp.Nullif)


@dataclass(frozen=True)
class ContractMetricTerm:
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


# -------------------------READ---------------------------
def parse_contract_metric(expression: str) -> ContractMetricFormula | None:
    try:
        tree = _unwrapped(sqlglot.parse_one(expression))
    except SqlglotError:
        return None
    if any(not isinstance(node, (*CONTRACT_METRIC_NODES, *RATIO_NODES)) for node in tree.walk()):
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


def formula_row_kinds(formula: ContractMetricFormula, row_kind_column: str | None) -> set[str]:
    terms = [formula.numerator, *([formula.denominator] if formula.denominator else [])]
    return {
        row_kind
        for term in terms
        for node in _conjuncts(term.condition)
        if (row_kind := _row_kind_value(node, row_kind_column))
    }


# -------------------------HELPERS------------------------
def _unwrapped(node: Any) -> Any:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _contract_term(node: Any) -> ContractMetricTerm | None:
    if not isinstance(node, AGGREGATES):
        return None
    inner = [child for child in node.walk() if child is not node]
    if any(not isinstance(child, CONTRACT_METRIC_NODES) or isinstance(child, AGGREGATES) for child in inner):
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
    if isinstance(node, exp.Literal) and node.is_number and "." in node.this:
        try:
            return node.this if float(node.this) > 0 else None
        except ValueError:
            return None
    return None


def _ratio(tree: Any) -> tuple[ContractMetricTerm, ContractMetricTerm, str] | None:
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


def _conjuncts(condition: str | None) -> list[Any]:
    if not condition:
        return []
    try:
        tree = _unwrapped(sqlglot.parse_one(condition, read="postgres"))
    except SqlglotError:
        return []
    if isinstance(tree, exp.And):
        return [*_conjuncts(tree.left.sql(dialect="postgres")), *_conjuncts(tree.right.sql(dialect="postgres"))]
    return [tree]


def _row_kind_value(node: Any, row_kind_column: str | None) -> str | None:
    node = _unwrapped(node)
    if not row_kind_column or not isinstance(node, exp.EQ):
        return None
    column, value = node.this, node.expression
    if isinstance(column, exp.Column) and column.name == row_kind_column and isinstance(value, exp.Literal):
        return value.this if value.is_string else None
    return None
