from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.public_metadata import metric_metadata
from text_to_bi.superset_ai_agent.modules.superset.services.chart_data import read_chart_queries

from ..exceptions import ApprovedMetricDatasetRequiredError
from .members import build_members_payload, build_time_range_payload, labelled_key_columns, members_from_rows, stored_label_members, temporal_columns, time_ranges_from_rows
from .metadata import require_dataset_context


def member_rows(dataset: Any, key_column: str, label_columns: list[str]) -> list[dict[str, Any]] | None:
    results = read_chart_queries(build_members_payload(dataset, key_column, label_columns))
    return None if not results or results[0].get("error") else results[0].get("data", [])


def read_dimension_members(dataset_id: int, cookie: str) -> dict[str, Any]:
    dataset, dictionary, entries, _grains, _layer = require_dataset_context(dataset_id, cookie)
    metrics = metric_metadata(cookie)["metrics"]
    if dictionary.dataset_type != "aggregate" and not any(metric["dataset_id"] == dataset_id and metric["state"] == "approved" for metric in metrics):
        raise ApprovedMetricDatasetRequiredError()
    labels = {column.column_name: column.verbose_name for column in dataset.columns}
    dimensions = []

    def append_dimension(key_column: str, label_column: str, members: list[dict[str, Any]]) -> None:
        dimensions.append({"key_column": key_column, "label_column": label_column, "label": labels.get(label_column) or label_column, "members": members})

    for key_column, label_column in labelled_key_columns(dataset):
        rows = member_rows(dataset, key_column, [label_column])
        if rows is not None:
            append_dimension(key_column, label_column, members_from_rows(rows, key_column, label_column))
    for key_column, label_column, members in stored_label_members(dataset, entries, lambda key, labels: member_rows(dataset, key, labels)):
        append_dimension(key_column, label_column, members)
    columns = temporal_columns(dataset)
    results = read_chart_queries(build_time_range_payload(dataset, columns)) if columns else None
    time_ranges = time_ranges_from_rows(results[0].get("data", []), columns) if results and not results[0].get("error") else []
    return {"dataset_id": dataset_id, "dimensions": dimensions, "time_ranges": time_ranges}
