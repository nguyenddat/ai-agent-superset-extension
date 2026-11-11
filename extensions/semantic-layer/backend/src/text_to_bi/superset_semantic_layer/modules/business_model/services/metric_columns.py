import re
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Jinja statements and comments, and the values Superset fills in, which no SQL parser reads.
_JINJA_TAG = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_JINJA_VALUE = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def _is_filter(column: exp.Column) -> bool:
    """Whether a column picks the rows a metric covers rather than being the value it aggregates.

    That is a column in a CASE condition (or the subject of a simple CASE x WHEN …), in an IF condition, in an
    aggregate's FILTER (WHERE ...) clause, or in a window's PARTITION BY or ORDER BY.
    """
    node: exp.Expression = column
    while node.parent is not None:
        parent = node.parent
        if isinstance(parent, (exp.If, exp.Case)) and node is parent.args.get("this"):
            return True
        if isinstance(parent, exp.Filter) and node is parent.expression:
            return True
        if isinstance(parent, exp.Window):
            partition = parent.args.get("partition_by") or []
            if node is parent.args.get("order") or any(node is item for item in partition):
                return True
        node = parent
    return False


def _parsed(expression: str, dialect: str | None) -> exp.Expression | None:
    """The expression's syntax tree, or None when it cannot be parsed.

    A templated expression is read again with its Jinja tags removed and each ``{{ … }}`` taken as NULL, so the
    columns written in every branch of the template still count.
    """
    attempts = [expression]
    untemplated = _JINJA_VALUE.sub(" NULL ", _JINJA_TAG.sub(" ", expression))
    if untemplated != expression:
        attempts.append(untemplated)
    for text in attempts:
        try:
            tree = sqlglot.parse_one(text, read=dialect)
        except SqlglotError:
            continue
        if tree is not None:
            return tree
    return None


def metric_columns(expression: str | None, column_names: list[str], dialect: str | None) -> list[dict[str, Any]] | None:
    """The dataset columns a metric expression uses, each with its role: ``measure`` or ``filter``.

    The expression is read with sqlglot, so any SQL form counts: DISTINCT, CASE, FILTER, COALESCE, NULLIF, casts,
    arithmetic between aggregates, nested and window functions, quoted or table-qualified columns. Columns are matched
    to ``column_names``, exactly or else ignoring case, and anything else the parser takes for a column (an alias, a
    typo) is left out. A column used both ways counts as a measure. None when the expression cannot be parsed even
    without its Jinja templating, so callers fall back to the dataset as a whole.
    """
    if not expression or not expression.strip():
        return []
    tree = _parsed(expression, dialect)
    if tree is None:
        return None
    exact = set(column_names)
    folded = {name.lower(): name for name in column_names}
    roles: dict[str, str] = {}
    for column in tree.find_all(exp.Column):
        name = column.name if column.name in exact else folded.get(column.name.lower())
        if name is None:
            continue
        role = "filter" if _is_filter(column) else "measure"
        roles[name] = "measure" if roles.get(name) == "measure" else role
    # Dataset column order keeps the result stable between requests.
    return [{"name": name, "role": roles[name]} for name in column_names if name in roles]
