from types import SimpleNamespace
from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.public_metadata import dictionary_metadata
from text_to_bi.superset_ai_agent.modules.superset.services.chart_data import read_chart_queries

from ..exceptions import QueryDatasetNotFoundError
from .members import build_values_payload, coded_value_columns, coded_values_from_rows


def dataset_context(row: dict[str, Any]) -> tuple[Any, Any, dict[str, Any], list[Any], Any]:
    database = row["database"]
    dataset = SimpleNamespace(id=row["id"], table_name=row["name"], schema=row["schema"], description=row.get("description"), database_id=database["id"],
                              sql="virtual" if row["is_virtual"] else None, columns=[SimpleNamespace(**column) for column in row["columns"]])
    dictionary = SimpleNamespace(**row["dictionary"])
    entries = {entry["column_name"]: SimpleNamespace(**entry) for entry in row["dictionary_columns"]}
    return dataset, dictionary, entries, [SimpleNamespace(**grain) for grain in row["grains"]], SimpleNamespace(**row["layer"]) if row["layer"] else None


def require_dataset_context(dataset_id: int, cookie: str) -> tuple[Any, Any, dict[str, Any], list[Any], Any]:
    row = next((row for row in dictionary_metadata(cookie)["datasets"] if row["id"] == dataset_id), None)
    if row is None:
        raise QueryDatasetNotFoundError()
    return dataset_context(row)


def coded_values(dataset: Any, entries: dict[str, Any]) -> dict[str, list[str]]:
    columns = coded_value_columns(dataset, entries)
    if not columns:
        return {}
    results = read_chart_queries(build_values_payload(dataset, columns))
    if results is None:
        return {}
    coded = {}
    for name, result in zip(columns, results):
        values = None if result.get("error") else coded_values_from_rows(result.get("data", []), name)
        if values:
            coded[name] = values
    return coded
