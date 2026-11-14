from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_metric import MetricDefinition


class MetricDefinitionRepository(BaseRepository[MetricDefinition]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricDefinition)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> MetricDefinition:
        return self.add(MetricDefinition(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, definition_id: int) -> MetricDefinition | None:
        return self.get(definition_id)

    def read_by_metric(self, metric_id: int) -> MetricDefinition | None:
        return self.query().filter(MetricDefinition.metric_id == metric_id).one_or_none()

    def read_on_datasets(self, dataset_ids: Iterable[int]) -> list[MetricDefinition]:
        dataset_ids = list(dataset_ids)
        if not dataset_ids:
            return []
        return self.query().filter(MetricDefinition.dataset_id.in_(dataset_ids)).all()

    # -------------------------UPDATE---------------------------
    def update(self, definition: MetricDefinition, values: dict[str, Any]) -> MetricDefinition:
        return super().update(definition, values)

    # -------------------------DELETE---------------------------
    def delete(self, definition: MetricDefinition) -> None:
        super().delete(definition)
