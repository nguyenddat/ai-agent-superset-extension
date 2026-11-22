from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetMetric

from ..models import Metric


class MetricRepository(BaseRepository[Metric]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Metric)

    def get(self, metric_id: UUID, lock: bool = False) -> Metric | None:
        statement = select(Metric).where(Metric.id == metric_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list(self, dataset_id: int) -> list[Metric]:
        return list(self.session.scalars(select(Metric).where(Metric.dataset_id == dataset_id).order_by(Metric.name)))

    def find_name(self, dataset_id: int, name: str) -> Metric | None:
        return self.session.scalar(select(Metric).where(
            Metric.dataset_id == dataset_id, func.lower(Metric.name) == name.lower()
        ))

    def native(self, dataset_id: int) -> list[SupersetMetric]:
        return list(self.session.scalars(select(SupersetMetric).where(
            SupersetMetric.table_id == dataset_id
        ).order_by(SupersetMetric.metric_name)))

    def native_by_id(self, metric_id: int) -> SupersetMetric | None:
        return self.session.get(SupersetMetric, metric_id)
