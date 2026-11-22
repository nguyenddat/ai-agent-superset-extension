from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from ..exceptions import DataLineageValidationError


def preview_sql(sql_text: str, target_dataset: Any, datasets: dict[int, Any]) -> dict[str, Any]:
    try:
        statements = [statement for statement in parse(sql_text, read="postgres") if statement is not None]
    except SqlglotError:
        raise DataLineageValidationError("Không phân tích được cú pháp SQL PostgreSQL.") from None
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise DataLineageValidationError("Xem trước chỉ nhận một câu SELECT.")
    statement = statements[0]
    if statement.args.get("with_") or any(statement.find_all(exp.Subquery, exp.Union)):
        return {
            "target_dataset_id": target_dataset.id, "source_dataset_ids": [], "dependencies": [],
            "warnings": ["CTE, subquery hoặc UNION cần khai báo nguồn và cột thủ công."], "complete": False,
        }

    warnings: list[str] = []
    aliases: dict[str, int] = {}
    source_dataset_ids: list[int] = []
    sources = [statement.args.get("from_")]
    sources.extend(statement.args.get("joins") or [])
    for source in sources:
        expression = source.this if source is not None else None
        if not isinstance(expression, exp.Table):
            warnings.append("Nguồn không phải bảng trực tiếp; cần khai báo thủ công.")
            continue
        matches = [
            dataset_id for dataset_id, dataset in datasets.items()
            if dataset.table_name == expression.name
            and (not expression.db or dataset.schema == expression.db)
        ]
        if len(matches) != 1:
            warnings.append(f"Không xác định duy nhất dataset nguồn {expression.sql()}.")
            continue
        dataset_id = matches[0]
        aliases[expression.alias_or_name] = dataset_id
        if dataset_id not in source_dataset_ids:
            source_dataset_ids.append(dataset_id)

    target_columns = {str(column.column_name): str(column.column_name) for column in target_dataset.columns or []}
    source_columns = {
        dataset_id: {str(column.column_name) for column in datasets[dataset_id].columns or []}
        for dataset_id in source_dataset_ids
    }
    dependencies: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str | None, str]] = set()

    def add_columns(expression: exp.Expression, role: str, target_column: str | None = None) -> None:
        for column in expression.find_all(exp.Column):
            if column.is_star:
                warnings.append("SELECT * cần xác nhận ánh xạ cột thủ công.")
                continue
            if column.table:
                candidates = [aliases[column.table]] if column.table in aliases else []
            else:
                candidates = [dataset_id for dataset_id, known in source_columns.items() if column.name in known]
            matched = [dataset_id for dataset_id in candidates if column.name in source_columns.get(dataset_id, set())]
            if len(matched) != 1:
                warnings.append(f"Không xác định duy nhất cột nguồn {column.sql()}.")
                continue
            key = (matched[0], column.name, target_column, role)
            if key not in seen:
                seen.add(key)
                dependencies.append({
                    "source_dataset_id": matched[0], "source_column_name": column.name,
                    "target_column_name": target_column, "role": role,
                })

    for projection in statement.expressions:
        if isinstance(projection, exp.Star) or projection.find(exp.Star):
            warnings.append("SELECT * cần xác nhận ánh xạ cột thủ công.")
            continue
        target_column = target_columns.get(projection.alias_or_name)
        if target_column is None:
            warnings.append(f"Không tìm thấy cột đích cho {projection.sql()}.")
            continue
        add_columns(projection, "value", target_column)
    for join in statement.args.get("joins") or []:
        if join.args.get("on"):
            add_columns(join.args["on"], "join")
        if join.args.get("using"):
            warnings.append("JOIN USING cần xác nhận cột join thủ công.")
    for key, role in (("group", "group"), ("where", "filter"), ("having", "filter")):
        if statement.args.get(key):
            add_columns(statement.args[key], role)
    if statement.find(exp.Window):
        warnings.append("Hàm cửa sổ cần kiểm tra lại các cột phụ thuộc.")
    return {
        "target_dataset_id": target_dataset.id, "source_dataset_ids": source_dataset_ids,
        "dependencies": dependencies, "warnings": list(dict.fromkeys(warnings)), "complete": not warnings,
    }
