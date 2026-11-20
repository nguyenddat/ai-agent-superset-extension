import json
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_datetime
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import user_names

from ..models import MetricContract, MetricContractEvent, MetricDefinition
from ..services.srv_metric_contract import MetricEntry
from ..services.srv_metric_formula import parse_contract_metric
from ..services.srv_metric_query_defaults import DatasetTimeContext


# -------------------------METRIC DEFINITION--------------
def serialize_metric_definition(definition: MetricDefinition | None) -> dict[str, Any] | None:
    if definition is None:
        return None
    try:
        default_filters = json.loads(definition.default_filters) if definition.default_filters else []
    except ValueError:
        default_filters = []
    return {
        "business_definition": definition.business_definition,
        "unit": definition.unit,
        "steward_id": definition.steward_id,
        "steward_name": user_names()(definition.steward_id),
        "grain": definition.grain,
        "row_kind_value": definition.row_kind_value,
        "time_column": definition.time_column,
        "time_window": definition.time_window,
        "time_anchor": definition.time_anchor,
        "default_filters": default_filters,
    }


# -------------------------METRIC CONTRACT----------------
def serialize_metric_contract(contract: MetricContract | None, metric: Any, state: str) -> dict[str, Any]:
    if contract is None:
        return {"metric_id": metric.id, "metric_name": metric.metric_name, "state": state}
    user_name = user_names()
    return {
        "id": contract.id,
        "dataset_id": contract.dataset_id,
        "metric_id": contract.metric_id,
        "metric_name": metric.metric_name,
        "status": contract.status,
        "state": state,
        "current": state == "approved",
        "origin": contract.origin,
        "owner_id": contract.owner_id,
        "owner_name": user_name(contract.owner_id),
        "approver_id": contract.approver_id,
        "approver_name": user_name(contract.approver_id),
        "approved_at": iso_datetime(contract.approved_at),
        "revoker_id": contract.revoker_id,
        "revoker_name": user_name(contract.revoker_id),
        "revoked_at": iso_datetime(contract.revoked_at),
    }


# -------------------------METRIC EVENT-------------------
def serialize_metric_events(events: list[MetricContractEvent]) -> list[dict[str, Any]]:
    user_name = user_names()
    return [
        {
            "id": event.id,
            "action": event.action,
            "actor_id": event.actor_id,
            "actor_name": user_name(event.actor_id),
            "reason": event.reason,
            "expression": event.expression,
            "created_at": iso_datetime(event.created_at),
        }
        for event in events
    ]


# -------------------------METRIC LIST--------------------
def serialize_metric_entry(entry: MetricEntry) -> dict[str, Any]:
    metric = entry.metric
    formula = parse_contract_metric(str(metric.expression or ""))
    return {
        "dataset_id": entry.dataset.id,
        "metric_id": metric.id,
        "metric_name": metric.metric_name,
        "verbose_name": metric.verbose_name,
        "description": metric.description,
        "expression": metric.expression,
        "d3format": metric.d3format,
        "formula": formula.as_dict() if formula else None,
        "ineligibility": entry.ineligibility,
        "state": entry.state,
        "query_defaults": entry.defaults.as_dict() if entry.defaults else None,
        "contract": serialize_metric_contract(entry.contract, metric, entry.state) if entry.contract else None,
        "definition": serialize_metric_definition(entry.definition),
    }


def serialize_query_dataset(dataset: Any, column_labels: dict[str, str], context: DatasetTimeContext) -> dict[str, Any]:
    columns = [
        {
            "column_name": column.column_name,
            "verbose_name": column_labels.get(column.column_name) or column.verbose_name,
            "type": column.type,
            "is_dttm": bool(column.is_dttm),
            "groupby": column.groupby is True,
            "filterable": column.filterable is True,
        }
        for column in dataset.columns
        if column.is_active is True and not column.expression and (column.groupby is True or column.filterable is True)
    ]
    return {
        "id": dataset.id,
        "name": f"{dataset.schema}.{dataset.table_name}" if dataset.schema else dataset.table_name,
        "columns": columns,
        "time_column": context.time_column,
        "row_kind_column": context.row_kind_column,
        "row_kinds": [
            {"value": value, "label": context.row_kind_labels.get(value), "grain": grain}
            for value, grain in context.grains.items()
        ],
        "temporal_columns": sorted(context.temporal_columns),
    }


def serialize_users(users: list[Any]) -> list[dict[str, Any]]:
    return [{"id": user.id, "name": user.get_full_name().strip() or user.username} for user in users]
