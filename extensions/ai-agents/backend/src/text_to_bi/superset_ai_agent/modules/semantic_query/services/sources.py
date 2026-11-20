from types import SimpleNamespace
from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.public_metadata import (
    dictionary_metadata,
    metric_metadata,
)

from .metadata import coded_values, dataset_context


def read_sources(cookie: str) -> dict[str, Any]:
    metadata = dictionary_metadata(cookie)
    metrics = metric_metadata(cookie)["metrics"]
    described = []
    for row in metadata["datasets"]:
        if row["dictionary"]["dataset_type"] not in ("base", "aggregate"):
            continue
        dataset, dictionary, entries, _grains, _layer = dataset_context(row)
        values = coded_values(dataset, entries)
        columns = source_columns(dataset, entries, {}, values)
        source_metrics = []
        if dictionary.dataset_type == "aggregate":
            for metric in metrics:
                if (
                    metric["dataset_id"] != dataset.id or metric["metric_name"] == "count"
                    or (metric["expression"] or "").replace(" ", "").upper() == "COUNT(*)"
                ):
                    continue
                live = SimpleNamespace(
                    id=metric["metric_id"], metric_name=metric["metric_name"], verbose_name=metric["label"],
                    expression=metric["expression"],
                )
                definition = SimpleNamespace(business_definition=metric["definition"], unit=metric["unit"])
                source_metrics.append(source_metric(live, metric["state"], metric["origin"], definition))
        described.append(
            {
                "id": dataset.id, "name": dataset.table_name, "label": dictionary.display_name,
                "dataset_type": dictionary.dataset_type, "description": dictionary.description,
                "grain": dictionary.grain, "columns": columns, "metrics": source_metrics,
            },
        )
    return {"datasets": sorted(described, key=lambda dataset: dataset["name"])}


def is_default_count(metric: Any) -> bool:
    expression = str(getattr(metric, "expression", "") or "").replace(" ", "").upper()
    return getattr(metric, "metric_name", None) == "count" or expression == "COUNT(*)"

def source_columns(
    dataset: Any, entries: dict[str, Any], referenced: dict[int, tuple[int, str]],
    coded_values: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    columns = []
    for column in getattr(dataset, "columns", []):
        if getattr(column, "is_active", None) is not True or getattr(column, "expression", None):
            continue
        entry = entries.get(str(column.column_name))
        described = {
            "name": column.column_name,
            "label": getattr(entry, "display_name", None) or getattr(column, "verbose_name", None),
            "type": str(column.type or ""),
            "unit": getattr(entry, "unit", None),
            "description": getattr(entry, "business_term", None),
            "temporal": bool(getattr(column, "is_dttm", False)),
            "groupby": getattr(column, "groupby", None) is True,
            "filterable": getattr(column, "filterable", None) is True,
        }
        explicit = getattr(entry, "references", None)
        target = referenced.get(getattr(entry, "referenced_column", None) or 0)
        if explicit is not None:
            described["references"] = explicit
        elif target is not None:
            described["references"] = {"dataset_id": target[0], "column": target[1]}
        if (coded_values or {}).get(str(column.column_name)):
            described["values"] = coded_values[str(column.column_name)]
        columns.append({key: value for key, value in described.items() if value not in (None, "")})
    return columns

def source_metric(metric: Any, state: str, origin: str | None, definition: Any) -> dict[str, Any]:
    described = {
        "metric_id": metric.id,
        "metric_name": metric.metric_name,
        "label": getattr(metric, "verbose_name", None),
        "expression": metric.expression,
        "state": state,
        "origin": origin,
        "definition": getattr(definition, "business_definition", None),
        "unit": getattr(definition, "unit", None),
    }
    return {key: value for key, value in described.items() if value not in (None, "")}
