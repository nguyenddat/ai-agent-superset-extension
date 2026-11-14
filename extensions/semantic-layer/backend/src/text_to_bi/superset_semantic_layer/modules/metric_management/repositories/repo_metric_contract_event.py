from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_metric import MetricContractEvent


class MetricContractEventRepository(BaseRepository[MetricContractEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricContractEvent)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> MetricContractEvent:
        return self.add(MetricContractEvent(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, event_id: int) -> MetricContractEvent | None:
        return self.get(event_id)

    def read_history(self, definition_id: int) -> list[MetricContractEvent]:
        return (
            self.query()
            .filter(MetricContractEvent.definition_id == definition_id)
            .order_by(MetricContractEvent.created_at.desc(), MetricContractEvent.id.desc())
            .all()
        )

    def read_history_by_metric(self, metric_id: int) -> list[MetricContractEvent]:
        return (
            self.query()
            .filter(MetricContractEvent.metric_id == metric_id)
            .order_by(MetricContractEvent.created_at.desc(), MetricContractEvent.id.desc())
            .all()
        )
