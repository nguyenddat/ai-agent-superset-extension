import re
from collections.abc import Mapping
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import json_list

from .srv_metric_formula import formula_row_kinds, parse_contract_metric

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

METRIC_CONTRACT_RULE = (
    "Công thức phải là đúng một AVG, COUNT, MAX, MIN hoặc SUM trên cột của dataset, có thể ở dạng "
    "CASE WHEN <so sánh cột với hằng số> THEN <cột hoặc số> END; hoặc tỷ lệ giữa hai hàm như vậy, viết "
    "<hệ số thập phân> * AGG(...) / NULLIF(AGG(...), 0), ví dụ 100.0 * ... cho phần trăm."
)

def metric_contract_ineligibility(dataset: Any, metric: Any) -> str | None:
    if not isinstance(metric.metric_name, str) or not IDENTIFIER.fullmatch(metric.metric_name):
        return "Tên metric chỉ được gồm chữ cái không dấu, chữ số và dấu gạch dưới."
    formula = parse_contract_metric(str(metric.expression or ""))
    if formula is None:
        return METRIC_CONTRACT_RULE
    live_columns = {column.column_name: column for column in dataset.columns}
    for column_name in sorted(formula.columns):
        column = live_columns.get(column_name)
        if column is None:
            return f"Cột {column_name} không có trong dataset."
        if column.is_active is not True:
            return f"Cột {column_name} đang bị tắt (không active)."
        if column.expression:
            return f"Cột {column_name} là cột tính toán."
    return None


def metric_is_eligible_for_contract(dataset: Any, metric: Any) -> bool:
    return metric_contract_ineligibility(dataset, metric) is None


def metric_semantic_ineligibility(
    dataset: Any,
    metric: Any,
    columns: Mapping[str, Any],
    metric_unit: str | None,
    grains: Mapping[str | None, str],
    row_kind_column: str | None = None,
) -> str | None:
    formula = parse_contract_metric(str(getattr(metric, "expression", None) or ""))
    if formula is None:
        return METRIC_CONTRACT_RULE
    terms = [formula.numerator, *([formula.denominator] if formula.denominator else [])]
    valid_roles = {"key", "measure", "dimension", "label", "time", "row_kind", "attribute"}
    for column_name in formula.columns:
        entry = columns.get(column_name)
        if entry is None:
            return f"Cột {column_name} chưa có khai báo ngữ nghĩa trong Từ điển dữ liệu."
        if getattr(entry, "semantic_role", None) not in valid_roles:
            return f"Cột {column_name} cần có vai trò ngữ nghĩa trong Từ điển dữ liệu."
    for term in terms:
        if term.measure_column:
            entry = columns.get(term.measure_column)
            if entry is None:
                return f"Cột {term.measure_column} chưa có khai báo ngữ nghĩa trong Từ điển dữ liệu."
            if getattr(entry, "semantic_role", None) != "measure":
                return f"Cột {term.measure_column} phải có vai trò measure để dùng làm giá trị metric."
            allowed = json_list(getattr(entry, "aggregations", None))
            if term.aggregation not in allowed:
                return f"Cột {term.measure_column} chưa cho phép phép tổng hợp {term.aggregation}."
    units = [
        "count" if term.aggregation == "COUNT" else getattr(columns.get(term.measure_column), "unit", None)
        for term in terms
        if term.measure_column or term.aggregation == "COUNT"
    ]
    normalized_units = {str(unit).strip().casefold() for unit in units if isinstance(unit, str) and unit.strip()}
    if len(normalized_units) > 1:
        return "Các thành phần của metric có đơn vị khác nhau; không thể cộng hoặc chia trực tiếp."
    normalized_metric_unit = metric_unit.strip().casefold() if isinstance(metric_unit, str) else ""
    if formula.denominator:
        if len(normalized_units) > 1:
            return "Các thành phần của metric có đơn vị khác nhau; không thể chia trực tiếp."
        if normalized_metric_unit and normalized_metric_unit not in {"%", "percent", "phần trăm", "ratio", "tỷ lệ"}:
            return "Metric là tỷ lệ nên đơn vị phải là %, percent, ratio hoặc tỷ lệ."
    elif (
        terms[0].aggregation == "COUNT" and normalized_metric_unit
        and normalized_metric_unit not in {"count", "bản ghi", "lượt"}
    ):
        return "Metric đếm phải có đơn vị count, bản ghi hoặc lượt."
    elif normalized_metric_unit and normalized_units and normalized_metric_unit not in normalized_units:
        return f"Đơn vị metric phải khớp đơn vị cột ({next(iter(normalized_units))})."
    formula_row_kind_values = formula_row_kinds(formula, row_kind_column)
    if len(formula_row_kind_values) > 1:
        return "Các thành phần của metric phải dùng cùng một loại dòng để có grain tương thích."
    if formula_row_kind_values:
        row_kind = next(iter(formula_row_kind_values))
        if row_kind not in grains:
            return f"Loại dòng {row_kind} chưa được khai báo grain trong Từ điển dữ liệu."
    return None
