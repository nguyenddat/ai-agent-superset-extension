from collections.abc import Callable
from datetime import datetime
from typing import Any

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.core.security import is_admin

from ..exceptions import ApprovedMetricContractRequiredError, MetricContractValidationError
from ..schemas.status_enum import ContractOrigin
from .srv_metric_contract import MetricContractService, contract_is_approved_current, metric_contract_state
from .srv_metric_data import latest_moment
from .srv_metric_limits import semantic_query_row_cap
from .srv_metric_query_defaults import (
    MetricQueryDefaults,
    applied_query_defaults,
    checked_query_filter,
    query_column,
    time_axis_column,
)

MAX_DIMENSIONS = 50
MAX_FILTERS = 50
QUERY_FIELDS = {"dimensions", "filters", "time_grain", "apply_defaults"}


def build_metric_chart_payload(
    dataset: Any, metric: Any, query: Any, max_rows: int, defaults: MetricQueryDefaults | None = None
) -> dict[str, Any]:
    return planned_metric_chart(dataset, metric, query, max_rows, defaults)[0]


def execute_approved_chart_query(
    contract: Any,
    dataset: Any,
    metric: Any,
    query: Any,
    max_rows: int,
    runner: Any,
    allow_candidate: bool = False,
    defaults: MetricQueryDefaults | None = None,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> Any:
    previewable = (
        allow_candidate and contract is not None
        and metric_contract_state(contract, dataset, metric, defaults) == "candidate"
    )
    if not previewable and not contract_is_approved_current(contract, dataset, metric, defaults):
        raise ApprovedMetricContractRequiredError()
    payload, applied = planned_metric_chart(dataset, metric, query, max_rows, defaults, latest_time)
    result = runner(payload)
    return {**result, "applied_defaults": applied} if applied is not None and isinstance(result, dict) else result


class MetricExecuteService:
    def __init__(self) -> None:
        self.contracts = MetricContractService()

    # -------------------------EXECUTE------------------------
    def execute(self, dataset: Any, metric: Any, query: Any, runner: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        contract = self.contracts.read(dataset, metric)
        if contract is None:
            raise ApprovedMetricContractRequiredError()
        defaults = self.contracts.query_defaults(dataset, metric)
        previewable = (is_admin() or contract.origin == ContractOrigin.AI_AGENT) and (
            metric_contract_state(contract, dataset, metric, defaults) == ReviewStatus.DRAFT.value
        )
        if not previewable and not contract_is_approved_current(contract, dataset, metric, defaults):
            raise ApprovedMetricContractRequiredError()

        def latest_time(filters: list[dict[str, Any]]) -> Any:
            return latest_moment(dataset, defaults.time_column, filters) if defaults and defaults.time_column else None

        max_rows = semantic_query_row_cap()
        payload, applied = planned_metric_chart(dataset, metric, query, max_rows, defaults, latest_time)
        result = runner(payload)
        rows = result.get("data", [])
        return {
            "error": result.get("error"),
            "columns": result.get("colnames", []),
            "rows": rows[:max_rows],
            "row_count": min(len(rows), max_rows),
            "truncated": len(rows) > max_rows,
            # The SQL Superset ran, RLS predicates included, so only administrators see it.
            "sql": result.get("query") if is_admin() else None,
            "preview": contract.status == ReviewStatus.DRAFT,
            "applied_defaults": applied,
        }


def run_chart_query(payload: dict[str, Any]) -> dict[str, Any]:
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
    command.validate()
    return command.run()["queries"][0]


# -------------------------PAYLOAD------------------------
def planned_metric_chart(
    dataset: Any,
    metric: Any,
    query: Any,
    max_rows: int,
    defaults: MetricQueryDefaults | None = None,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if isinstance(query, dict) and "joins" in query:
        raise MetricContractValidationError("Truy vấn metric không nối nhiều dataset.")
    if not isinstance(query, dict) or set(query) - QUERY_FIELDS:
        raise MetricContractValidationError("Truy vấn chỉ gồm dimensions, filters, time_grain và apply_defaults.")
    dimensions = query.get("dimensions", [])
    filters = query.get("filters", [])
    if not isinstance(dimensions, list) or not isinstance(filters, list):
        raise MetricContractValidationError("dimensions và filters phải là mảng.")
    if len(dimensions) > MAX_DIMENSIONS or len(filters) > MAX_FILTERS:
        raise MetricContractValidationError(
            f"Truy vấn có tối đa {MAX_DIMENSIONS} chiều phân tích và {MAX_FILTERS} bộ lọc."
        )
    apply_defaults = query.get("apply_defaults", True)
    if not isinstance(apply_defaults, bool):
        raise MetricContractValidationError("apply_defaults phải là true hoặc false.")

    columns = {str(column.column_name): column for column in dataset.columns}
    selected = [query_column(columns, name, "groupby") for name in dimensions]
    if len(set(selected)) != len(selected):
        raise MetricContractValidationError("Mỗi chiều phân tích chỉ chọn một lần.")
    chart_filters = [checked_query_filter(columns, item) for item in filters]
    default_filters, time_grain, applied = applied_query_defaults(
        defaults,
        {item["col"] for item in chart_filters},
        selected,
        query.get("time_grain"),
        apply_defaults,
        latest_time,
        now,
    )
    time_column = defaults.time_column if defaults else None
    chart_columns: list[Any] = [
        time_axis_column(name, time_grain) if time_grain and name == time_column else name for name in selected
    ]
    payload = {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [
            {
                "columns": chart_columns,
                "metrics": [metric.metric_name],
                "filters": chart_filters + default_filters,
                "row_limit": max_rows + 1,
            }
        ],
        "result_type": "full",
        "result_format": "json",
    }
    return payload, applied
