from typing import Any, ClassVar

import sqlglot
from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import SqlglotError

from .contracts import ContractMetricFormula

_AGGREGATE_WORDS = {exp.Sum: "TỔNG", exp.Avg: "TRUNG_BÌNH", exp.Count: "ĐẾM", exp.Max: "LỚN_NHẤT", exp.Min: "NHỎ_NHẤT"}
_OPERATORS = {
    exp.EQ: "=", exp.NEQ: "≠", exp.GT: ">", exp.GTE: "≥", exp.LT: "<", exp.LTE: "≤", exp.Mul: "×", exp.Div: "÷",
    exp.And: "VÀ", exp.Or: "HOẶC", exp.Like: "GIỐNG",
}


def _unwrapped(node: Any) -> Any:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _conjuncts(condition: str | None) -> list[Any]:
    """The parts of a condition joined by a top-level AND, each kept whole."""
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
    """The row kind a condition such as loai_quan_sat = 'DU_BAO_NGAY' selects, or None."""
    node = _unwrapped(node)
    if not row_kind_column or not isinstance(node, exp.EQ):
        return None
    column, value = node.this, node.expression
    if isinstance(column, exp.Column) and column.name == row_kind_column and isinstance(value, exp.Literal):
        return value.this if value.is_string else None
    return None


def formula_row_kinds(formula: ContractMetricFormula, row_kind_column: str | None) -> set[str]:
    """The row kinds the formula's conditions select, such as {"DU_BAO_NGAY"}; empty when it counts every kind."""
    terms = [formula.numerator, *([formula.denominator] if formula.denominator else [])]
    return {
        row_kind
        for term in terms
        for node in _conjuncts(term.condition)
        if (row_kind := _row_kind_value(node, row_kind_column))
    }


class _PseudoCodeGenerator(Postgres.Generator):
    """Writes a parsed metric expression as pseudo code: dictionary labels in brackets, Vietnamese words for the
    aggregates and the logic, and every other function or construct as it is in SQL, so nothing goes unsaid."""

    def __init__(self, column_labels: dict[str, str]):
        super().__init__(dialect="postgres", comments=False)
        self.column_labels = column_labels

    def column_label(self, column: exp.Column) -> str:
        label = self.column_labels.get(column.name)
        if label:
            return f"[{label}]"
        return f"[{column.table}.{column.name}]" if column.table else f"[{column.name}]"

    def literal_value(self, literal: exp.Literal) -> str:
        return f"“{literal.this}”" if literal.is_string else literal.this

    def aggregate(self, node: exp.Expression) -> str:
        argument = node.this
        if isinstance(node, exp.Count) and (argument is None or isinstance(argument, exp.Star)):
            return "ĐẾM(*)"
        return f"{_AGGREGATE_WORDS[type(node)]}({self.sql(argument)})"

    def operator(self, node: exp.Binary) -> str:
        joiner = "\n" if isinstance(node, exp.Div) and node.parent is None else " "
        return f"{self.sql(node.this)}{joiner}{_OPERATORS[type(node)]} {self.sql(node.expression)}"

    def branches(self, case: exp.Case) -> str:
        """CASE as NẾU … THÌ …, one branch after another; a simple CASE x WHEN v compares x = v in each branch."""
        subject = case.this
        parts = []
        for branch in case.args.get("ifs") or []:
            condition = self.sql(branch.this)
            if subject is not None:
                condition = f"{self.sql(subject)} = {condition}"
            parts.append(f"NẾU {condition} THÌ {self.sql(branch, 'true')}")
        if case.args.get("default") is not None:
            parts.append(f"CÒN LẠI {self.sql(case, 'default')}")
        text = ", ".join(parts)
        # Inside a function call its parentheses already set the branches apart.
        return text if case.parent is None or isinstance(case.parent, exp.Func) else f"({text})"

    def negated(self, node: exp.Not) -> str:
        inner = _unwrapped(node.this)
        if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
            return f"{self.sql(inner.this)} CÓ GIÁ TRỊ"
        if isinstance(inner, exp.In):
            return f"{self.sql(inner.this)} KHÔNG {self.membership(inner)}"
        if isinstance(inner, exp.Like):
            return f"{self.sql(inner.this)} KHÔNG GIỐNG {self.sql(inner.expression)}"
        return f"KHÔNG ({self.sql(inner)})" if isinstance(inner, exp.Binary) else f"KHÔNG {self.sql(inner)}"

    def membership(self, node: exp.In) -> str:
        if node.args.get("query"):
            return f"THUỘC {self.sql(node, 'query')}"
        return f"THUỘC ({', '.join(self.sql(item) for item in node.expressions)})"

    def null_check(self, node: exp.Is) -> str:
        if isinstance(node.expression, exp.Null):
            return f"{self.sql(node.this)} TRỐNG"
        return f"{self.sql(node.this)} LÀ {self.sql(node.expression)}"

    def window(self, node: exp.Window) -> str:
        parts = []
        if node.args.get("partition_by"):
            parts.append(f"CHIA THEO {', '.join(self.sql(item) for item in node.args['partition_by'])}")
        if node.args.get("order"):
            parts.append(f"XẾP THEO {', '.join(self.sql(item) for item in node.args['order'].expressions)}")
        if node.args.get("spec"):
            parts.append(self.sql(node, "spec"))
        return f"{self.sql(node.this)} TRÊN ({' '.join(parts)})"

    def ordered(self, node: exp.Ordered) -> str:
        return f"{self.sql(node.this)} GIẢM DẦN" if node.args.get("desc") else self.sql(node.this)

    TRANSFORMS: ClassVar[dict[Any, Any]] = {
        # PostgreSQL casts ROUND's argument to NUMERIC; the reading keeps ROUND as written.
        **{node: transform for node, transform in Postgres.Generator.TRANSFORMS.items() if node is not exp.Round},
        exp.Column: lambda self, node: self.column_label(node),
        exp.Literal: lambda self, node: self.literal_value(node),
        exp.Null: lambda self, node: "RỖNG",
        exp.Boolean: lambda self, node: "ĐÚNG" if node.this else "SAI",
        **{aggregate: lambda self, node: self.aggregate(node) for aggregate in _AGGREGATE_WORDS},
        exp.Distinct: lambda self, node: f"KHÁC NHAU {', '.join(self.sql(item) for item in node.expressions)}",
        **{operator: lambda self, node: self.operator(node) for operator in _OPERATORS},
        exp.Case: lambda self, node: self.branches(node),
        exp.If: lambda self, node: self.func("NẾU", node.this, node.args.get("true"), node.args.get("false")),
        exp.Not: lambda self, node: self.negated(node),
        exp.In: lambda self, node: f"{self.sql(node.this)} {self.membership(node)}",
        exp.Is: lambda self, node: self.null_check(node),
        exp.Between: lambda self, node: (
            f"{self.sql(node.this)} TỪ {self.sql(node, 'low')} ĐẾN {self.sql(node, 'high')}"
        ),
        exp.Filter: lambda self, node: f"{self.sql(node.this)} CHỈ KHI {self.sql(node.expression.this)}",
        exp.Window: lambda self, node: self.window(node),
        exp.Ordered: lambda self, node: self.ordered(node),
        exp.Cast: lambda self, node: f"ĐỔI_KIỂU({self.sql(node.this)}, {self.sql(node, 'to')})",
    }


def metric_pseudo_code(expression: str | None, column_labels: dict[str, str], dialect: str | None = None) -> str | None:
    """A metric expression as pseudo code for a reviewer, with the data dictionary's column labels in brackets.

    Aggregates, CASE, FILTER, windows, casts and the logic read in Vietnamese words; any other function keeps its SQL
    name, so every expression Superset accepts has a reading. None when the expression cannot be parsed, such as one
    holding Jinja templating; the raw SQL then stands alone.
    """
    if not expression or not expression.strip():
        return None
    try:
        tree = sqlglot.parse_one(expression, read=dialect)
    except SqlglotError:
        return None
    if tree is None:
        return None
    try:
        return _PseudoCodeGenerator(column_labels).generate(tree)
    except (SqlglotError, ValueError, KeyError):
        return None
