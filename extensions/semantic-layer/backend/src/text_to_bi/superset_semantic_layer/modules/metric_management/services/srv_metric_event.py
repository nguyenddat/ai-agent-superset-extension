from datetime import datetime, timezone
from typing import Any

from flask_login import current_user

from ..dependencies import metric_contract_event_repository
from ..models import MetricContract, MetricContractEvent, MetricDefinition
from .srv_metric_query_defaults import QUERY_DEFAULT_FIELDS

DEFINITION_FIELDS = ("business_definition", "unit", "steward_id", *QUERY_DEFAULT_FIELDS)


class MetricEventService:
    def __init__(self) -> None:
        self.events = metric_contract_event_repository()

    # -------------------------CREATE-------------------------
    def create(
        self,
        definition: MetricDefinition,
        metric: Any,
        action: str,
        reason: str | None = None,
        contract: MetricContract | None = None,
    ) -> MetricContractEvent:
        """Ghi một bước trong lịch sử duyệt, kèm ảnh chụp định nghĩa và công thức lúc đó."""
        return self.events.create(
            {
                "definition_id": definition.id,
                "metric_id": definition.metric_id,
                "dataset_id": definition.dataset_id,
                "metric_name": metric.metric_name,
                "action": action,
                "actor_id": current_user.id,
                "reason": reason,
                "expression": contract.expression if contract is not None else None,
                "expression_hash": contract.expression_hash if contract is not None else None,
                "definition_snapshot": {field: getattr(definition, field, None) for field in DEFINITION_FIELDS},
                "created_at": datetime.now(tz=timezone.utc),
            },
            flush=False,
        )

    # -------------------------READ---------------------------
    def read_history(self, metric: Any) -> list[MetricContractEvent]:
        """Lịch sử duyệt của metric, mới nhất trước; còn giữ cả khi định nghĩa đã bị xóa."""
        return self.events.read_history_by_metric(metric.id)
