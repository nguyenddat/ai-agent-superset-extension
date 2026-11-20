from collections.abc import Callable, Iterable, Mapping
from typing import Any

from text_to_bi.superset_semantic_layer.core.security import can_access_dataset
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_relationship_contract import (
    RelationshipEnd,
    relationship_is_approved_current,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    datasets_by_name,
    is_internal_dataset,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import user_names

from ..dependencies import metric_contract_repository, metric_definition_repository
from .srv_metric_contract import contract_is_approved_current, metric_contract_state
from .srv_metric_limits import semantic_query_row_cap
from .srv_metric_query_defaults import query_defaults_on

FILTER_OPERATORS = ["==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"]


def build_semantic_catalog(
    datasets: Mapping[int, Any],
    metric_contracts: Iterable[Any],
    relationships: Iterable[tuple[Any, RelationshipEnd, RelationshipEnd]],
    can_access: Callable[[Any], bool],
    max_rows: int,
    metric_details: Callable[[int, int], Mapping[str, Any]] | None = None,
    query_defaults: Mapping[tuple[int, int], Any] | None = None,
) -> dict[str, Any]:
    access: dict[int, bool] = {}

    def allowed(dataset: Any) -> bool:
        dataset_id = getattr(dataset, "id", None)
        if dataset_id not in access:
            access[dataset_id] = bool(can_access(dataset))
        return access[dataset_id]

    catalog: dict[int, dict[str, Any]] = {}
    for contract in metric_contracts:
        dataset = datasets.get(getattr(contract, "dataset_id", None))
        if dataset is None or not allowed(dataset):
            continue
        metric = next((item for item in getattr(dataset, "metrics", []) if item.id == contract.metric_id), None)
        defaults = (query_defaults or {}).get((dataset.id, contract.metric_id))
        if metric is None or not contract_is_approved_current(contract, dataset, metric, defaults):
            continue
        catalog.setdefault(
            dataset.id, {"id": dataset.id, "name": dataset.table_name, "metrics": [], "dimensions": []}
        )["metrics"].append(
            {
                "metric_id": metric.id, "metric_name": metric.metric_name,
                "verbose_name": getattr(metric, "verbose_name", None),
                "description": getattr(metric, "description", None),
                "d3format": getattr(metric, "d3format", None),
                "query_defaults": defaults.as_dict() if defaults else None,
                **(metric_details(dataset.id, metric.id) if metric_details else {}),
            }
        )
    visible_relationships = []
    for contract, source, target in relationships:
        if source.dataset.id not in datasets or target.dataset.id not in datasets:
            continue
        if (
            not (allowed(source.dataset) and allowed(target.dataset))
            or not relationship_is_approved_current(contract, source, target)
        ):
            continue
        for dataset in (source.dataset, target.dataset):
            catalog.setdefault(
                dataset.id, {"id": dataset.id, "name": dataset.table_name, "metrics": [], "dimensions": []}
            )
        visible_relationships.append({
            "id": contract.id, "from_dataset_id": contract.from_dataset_id, "from_column": contract.from_column,
            "to_dataset_id": contract.to_dataset_id, "to_column": contract.to_column,
            "cardinality": contract.cardinality, "executable": False,
        })
    for dataset_id, item in catalog.items():
        dataset = datasets.get(dataset_id)
        if dataset is None:
            continue
        item["metrics"].sort(key=lambda metric: (metric["metric_name"], metric["metric_id"]))
        item["dimensions"] = [
            {
                "name": column.column_name, "label": getattr(column, "verbose_name", None),
                "type": getattr(column, "type", None), "temporal": bool(getattr(column, "is_dttm", False)),
                "groupby": bool(getattr(column, "groupby", False)),
                "filterable": bool(getattr(column, "filterable", False)),
            }
            for column in getattr(dataset, "columns", [])
            if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
            and (getattr(column, "groupby", None) is True or getattr(column, "filterable", None) is True)
        ]
    return {
        "datasets": [catalog[key] for key in sorted(catalog)],
        "relationships": sorted(visible_relationships, key=lambda item: item["id"]),
        "limits": {"max_rows": max_rows, "filter_operators": FILTER_OPERATORS, "joins_supported": False},
    }


def read_query_metrics() -> dict[str, Any]:
    datasets = [
        dataset for dataset in datasets_by_name() if not is_internal_dataset(dataset) and can_access_dataset(dataset)
    ]
    dataset_ids = [dataset.id for dataset in datasets]
    contracts = {
        (contract.dataset_id, contract.metric_id): contract
        for contract in metric_contract_repository().read_on_datasets(dataset_ids)
    }
    definitions = {
        (definition.dataset_id, definition.metric_id): definition
        for definition in metric_definition_repository().read_on_datasets(dataset_ids)
    }
    defaults = query_defaults_on(dataset_ids)
    user_name = user_names()
    result = []
    for dataset in datasets:
        for metric in dataset.metrics:
            key = (dataset.id, metric.id)
            contract, definition, query_defaults = contracts.get(key), definitions.get(key), defaults.get(key)
            result.append({
                "dataset_id": dataset.id, "metric_id": metric.id, "metric_name": metric.metric_name,
                "label": metric.verbose_name, "expression": metric.expression, "description": metric.description,
                "d3format": metric.d3format,
                "state": metric_contract_state(contract, dataset, metric, query_defaults),
                "origin": getattr(contract, "origin", None),
                "definition": getattr(definition, "business_definition", None),
                "unit": getattr(definition, "unit", None),
                "steward_name": user_name(definition.steward_id) if definition else None,
                "query_defaults": query_defaults.as_dict() if query_defaults else None,
            })
    return {"metrics": result, "limits": {"max_rows": semantic_query_row_cap()}}
