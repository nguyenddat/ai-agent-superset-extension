from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

_COMPARISONS = {
    exp.EQ: "là",
    exp.NEQ: "khác",
    exp.GT: "lớn hơn",
    exp.GTE: "từ",
    exp.LT: "nhỏ hơn",
    exp.LTE: "không quá",
}
_AGGREGATE_WORDS = {"SUM": "Tổng", "AVG": "Trung bình", "MAX": "Giá trị lớn nhất của", "MIN": "Giá trị nhỏ nhất của"}

Part = dict[str, str]


class _Untold(Exception):
    pass


def _text(value: str) -> Part:
    return {"text": value}


def _value(node: exp.Expression) -> list[Part]:
    if isinstance(node, exp.Literal):
        return [_text(f"“{node.this}”" if node.is_string else node.this)]
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return [_text(f"-{node.this.this}")]
    if isinstance(node, exp.Boolean):
        return [_text("đúng" if node.this else "sai")]
    raise _Untold


def _condition(node: exp.Expression, column_part) -> list[Part]:
    if isinstance(node, exp.Paren):
        return _condition(node.this, column_part)
    if isinstance(node, (exp.And, exp.Or)):
        joiner = " và " if isinstance(node, exp.And) else " hoặc "
        return [*_condition(node.left, column_part), _text(joiner), *_condition(node.right, column_part)]
    if isinstance(node, exp.Not):
        return [_text("không phải ("), *_condition(node.this, column_part), _text(")")]
    if isinstance(node, exp.Is) and isinstance(node.left, exp.Column) and isinstance(node.right, exp.Null):
        return [column_part(node.left), _text(" trống")]
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column) and node.expressions:
        values: list[Part] = []
        for index, item in enumerate(node.expressions):
            values += ([_text(", ")] if index else []) + _value(item)
        return [column_part(node.this), _text(" thuộc "), *values]
    if isinstance(node, exp.Between) and isinstance(node.this, exp.Column):
        low, high = _value(node.args["low"]), _value(node.args["high"])
        return [column_part(node.this), _text(" từ "), *low, _text(" đến "), *high]
    word = _COMPARISONS.get(type(node))
    if word and isinstance(node.left, exp.Column):
        suffix = [_text(" trở lên")] if isinstance(node, exp.GTE) else []
        return [column_part(node.left), _text(f" {word} "), *_value(node.right), *suffix]
    raise _Untold


def _told_aggregate(tree: exp.Expression, column_part) -> list[Part]:
    if not isinstance(tree, (exp.Sum, exp.Avg, exp.Max, exp.Min, exp.Count)):
        raise _Untold
    measure, condition = tree.this, None
    if isinstance(measure, exp.Case):
        branches = measure.args.get("ifs") or []
        default = measure.args.get("default")
        if len(branches) != 1 or not (default is None or isinstance(default, exp.Null)):
            raise _Untold
        condition = _condition(branches[0].this, column_part)
        measure = branches[0].args.get("true")
    # COUNT of a constant and SUM of 1 both count the rows that meet the condition.
    counts_constant = isinstance(tree, exp.Count) and (measure is None or isinstance(measure, (exp.Literal, exp.Star)))
    sums_one = isinstance(tree, exp.Sum) and isinstance(measure, exp.Literal) and measure.this == "1"
    counted_rows = counts_constant or sums_one
    if counted_rows:
        sentence = [_text("Đếm số dòng")]
    elif isinstance(measure, exp.Column):
        word = "Đếm số" if isinstance(tree, exp.Count) else _AGGREGATE_WORDS[tree.key.upper()]
        sentence = [_text(f"{word} "), column_part(measure)]
    elif isinstance(measure, (exp.Literal, exp.Neg)) and not isinstance(tree, exp.Count):
        sentence = [_text(f"{_AGGREGATE_WORDS[tree.key.upper()]} giá trị "), *_value(measure)]
    else:
        raise _Untold
    if condition is not None:
        sentence += [_text(" có " if counted_rows else ", chỉ tính các dòng có "), *condition]
    return sentence


def _unwrapped(node: exp.Expression) -> exp.Expression:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _lowercased(parts: list[Part]) -> list[Part]:
    first = parts[0]["text"]
    return [_text(first[:1].lower() + first[1:]), *parts[1:]]


def _told_ratio(tree: exp.Expression, column_part) -> list[Part]:
    if not isinstance(tree, exp.Div):
        raise _Untold
    scaled, guarded = _unwrapped(tree.this), _unwrapped(tree.expression)
    if not isinstance(scaled, exp.Mul) or not isinstance(guarded, exp.Nullif):
        raise _Untold
    left, right = _unwrapped(scaled.this), _unwrapped(scaled.expression)
    scale, numerator = (left, right) if isinstance(left, exp.Literal) else (right, left)
    if not isinstance(scale, exp.Literal) or not scale.is_number:
        raise _Untold
    ratio = "Tỷ lệ phần trăm" if float(scale.this) == 100 else f"Tỷ lệ (nhân {scale.this})"
    return [
        _text(f"{ratio} giữa ("), *_lowercased(_told_aggregate(numerator, column_part)),
        _text(") và ("), *_lowercased(_told_aggregate(_unwrapped(guarded.this), column_part)), _text(")"),
    ]


def told_formula(expression: str, columns: list[dict[str, Any]]) -> list[Part] | None:
    labels = {column["name"]: column.get("label") or column["name"] for column in columns}

    def column_part(node: exp.Column) -> Part:
        if node.table or node.name not in labels:
            raise _Untold
        return {"column": node.name, "label": labels[node.name]}

    try:
        tree = _unwrapped(sqlglot.parse_one(expression, read="postgres"))
    except SqlglotError:
        return None
    try:
        if isinstance(tree, exp.Div):
            return _told_ratio(tree, column_part)
        return _told_aggregate(tree, column_part)
    except _Untold:
        return None


def doubtful_result(result: dict[str, Any]) -> str | None:
    if (result.get("coverage") or {}).get("status") == "none":
        return None
    if not result.get("total_rows"):
        return "empty"
    names = [metric["name"] for metric in result.get("metrics", [])]
    values = [row.get(name) for row in result.get("rows", []) for name in names]
    complete = result.get("row_count") == result.get("total_rows") and not result.get("truncated")
    if complete and values and all(value in (0, None) for value in values):
        return "zero"
    return None


def answers_anything(answer: dict[str, Any], metric_name: str) -> bool:
    for row in answer.get("rows", []):
        try:
            # The Semantic Layer returns numbers as numbers or as decimal strings such as "0.0000".
            if float(row.get(metric_name)) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False
