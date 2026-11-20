import logging
import re
from collections.abc import Callable
from typing import Any

from text_to_bi.superset_semantic_layer.core.security import is_superset_access_error

from ....common.utils.type_formatter import iso_date

logger = logging.getLogger(__name__)

MAX_MEMBERS = 500
SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEXT_TYPE = re.compile(r"CHAR|TEXT|STRING", re.IGNORECASE)


def _physical_columns(dataset: Any) -> list[str]:
    return [
        str(column.column_name)
        for column in getattr(dataset, "columns", [])
        if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
        and getattr(column, "filterable", None) is True
    ]


def labelled_key_columns(dataset: Any) -> list[tuple[str, str]]:
    table = re.escape(str(dataset.table_name))
    physical = _physical_columns(dataset)
    pairs = []
    for column in getattr(dataset, "columns", []):
        expression = getattr(column, "expression", None)
        groupable = getattr(column, "is_active", None) is True and getattr(column, "groupby", None) is True
        if not groupable or not expression:
            continue
        referenced = [name for name in physical if re.search(rf"\b{table}\.{re.escape(name)}\b", expression)]
        if len(referenced) == 1:
            pairs.append((referenced[0], str(column.column_name)))
    return pairs


def stored_label_candidates(dataset: Any, entries: dict[str, Any]) -> list[tuple[str, list[str]]]:
    groupable = [
        column for column in getattr(dataset, "columns", [])
        if getattr(column, "is_active", None) is True and getattr(column, "groupby", None) is True
        and not getattr(column, "expression", None) and SIMPLE_IDENTIFIER.match(str(column.column_name))
    ]

    def is_key(column: Any) -> bool:
        entry = entries.get(column.column_name)
        declared = getattr(entry, "semantic_role", None) == "key" or getattr(entry, "is_fk", False)
        names_rows = getattr(entry, "is_pk", False) or getattr(entry, "is_unique", False)
        return bool(declared) and not names_rows and not getattr(column, "is_dttm", False)

    def is_text(column: Any) -> bool:
        entry = entries.get(column.column_name)
        identifies = any(getattr(entry, flag, False) for flag in ("is_pk", "is_fk", "is_unique"))
        role = getattr(entry, "semantic_role", None)
        return bool(_TEXT_TYPE.search(str(getattr(column, "type", None) or ""))) and role != "key" and not identifies

    keys = [str(column.column_name) for column in groupable if is_key(column)]
    texts = [str(column.column_name) for column in groupable if is_text(column)]
    return [(key, texts) for key in keys] if texts else []


def build_members_payload(dataset: Any, key_column: str, label_columns: list[str]) -> dict[str, Any]:
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{
            "columns": [key_column, *label_columns],
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}],
            "row_limit": MAX_MEMBERS + 1,
        }],
        "result_type": "full",
        "result_format": "json",
    }


def members_from_rows(rows: list[dict[str, Any]], key_column: str, label_column: str) -> list[dict[str, Any]]:
    members = {
        row[key_column]: str(row[label_column])
        for row in rows[:MAX_MEMBERS]
        if row.get(key_column) is not None and row.get(label_column) not in (None, "")
    }
    return [{"value": value, "label": label} for value, label in sorted(members.items(), key=lambda item: item[1])]


def labels_from_rows(
    rows: list[dict[str, Any]], key_column: str, text_columns: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if len(rows) > MAX_MEMBERS:
        return {}
    labelled = {}
    for text_column in text_columns:
        values: dict[Any, set[str]] = {}
        for row in rows:
            if row.get(key_column) is not None and row.get(text_column) not in (None, ""):
                values.setdefault(row[key_column], set()).add(str(row[text_column]))
        if values and all(len(texts) == 1 for texts in values.values()):
            labelled[text_column] = members_from_rows(rows, key_column, text_column)
    return labelled


def stored_label_members(
    dataset: Any, entries: dict[str, Any], read_rows: Callable[[str, list[str]], list[dict[str, Any]] | None]
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    found = []
    for key_column, text_columns in stored_label_candidates(dataset, entries):
        for text_column in text_columns:
            rows = read_rows(key_column, [text_column]) or []
            for label_column, members in labels_from_rows(rows, key_column, [text_column]).items():
                found.append((key_column, label_column, members))
    return found


def temporal_columns(dataset: Any) -> list[str]:
    dated = {getattr(column, "column_name", None) for column in dataset.columns if getattr(column, "is_dttm", False)}
    return [name for name in _physical_columns(dataset) if name in dated and SIMPLE_IDENTIFIER.match(name)]


def build_time_range_payload(dataset: Any, columns: list[str]) -> dict[str, Any]:
    metrics = [
        {"expressionType": "SQL", "sqlExpression": f"{function}({name})", "label": f"{function.lower()}__{name}"}
        for name in columns for function in ("MIN", "MAX")
    ]
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{"columns": [], "metrics": metrics, "row_limit": 1}],
        "result_type": "full",
        "result_format": "json",
    }


def build_latest_time_payload(dataset: Any, column: str, filters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not SIMPLE_IDENTIFIER.match(column):
        return None
    metric = {"expressionType": "SQL", "sqlExpression": f"MAX({column})", "label": "latest_moment"}
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{"columns": [], "metrics": [metric], "filters": filters, "row_limit": 1}],
        "result_type": "full",
        "result_format": "json",
    }


def time_ranges_from_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    row = rows[0] if rows else {}
    ranges = [
        {"column": name, "min": iso_date(row.get(f"min__{name}")), "max": iso_date(row.get(f"max__{name}"))}
        for name in columns
    ]
    return [item for item in ranges if item["min"] and item["max"]]


MAX_CODED_VALUES = 20
MAX_CODE_LENGTH = 60


def coded_value_columns(dataset: Any, entries: dict[str, Any]) -> list[str]:
    text_columns = {
        str(column.column_name)
        for column in getattr(dataset, "columns", [])
        if _TEXT_TYPE.search(str(column.type or ""))
    }
    coded = []
    for name in _physical_columns(dataset):
        entry = entries.get(name)
        if name not in text_columns or not SIMPLE_IDENTIFIER.match(name):
            continue
        if any(getattr(entry, flag, False) for flag in ("is_pk", "is_fk", "is_unique")):
            continue
        coded.append(name)
    return coded


def build_values_payload(dataset: Any, columns: list[str]) -> dict[str, Any]:
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [
            {
                "columns": [name],
                "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}],
                "row_limit": MAX_CODED_VALUES + 1,
            }
            for name in columns
        ],
        "result_type": "full",
        "result_format": "json",
    }


def coded_values_from_rows(rows: list[dict[str, Any]], column: str) -> list[str] | None:
    values = {str(row[column]) for row in rows if row.get(column) not in (None, "")}
    if len(rows) > MAX_CODED_VALUES or any(len(value) > MAX_CODE_LENGTH for value in values):
        return None
    return sorted(values)


def latest_moment(dataset: Any, column: str, filters: list[dict[str, Any]]) -> Any:
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    payload = build_latest_time_payload(dataset, column, filters)
    if payload is None:
        return None
    try:
        command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
        command.validate()
        result = command.run()["queries"][0]
    except Exception as ex:
        if not is_superset_access_error(ex):
            logger.exception("Reading the latest %s of %s failed", column, dataset.table_name)
        return None
    rows = [] if result.get("error") else result.get("data", [])
    return rows[0].get("latest_moment") if rows else None
