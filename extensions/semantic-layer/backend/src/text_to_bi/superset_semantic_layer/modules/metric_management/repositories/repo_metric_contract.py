from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus

from ..models.model_metric import MetricContract, MetricDefinition


class MetricContractRepository(BaseRepository[MetricContract]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MetricContract)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> MetricContract:
        return self.add(MetricContract(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, contract_id: int) -> MetricContract | None:
        return self.get(contract_id)

    def read_by_definition(self, definition_id: int) -> MetricContract | None:
        return self.query().filter(MetricContract.definition_id == definition_id).one_or_none()

    def read_by_metric(self, metric_id: int) -> MetricContract | None:
        return (
            self.query()
            .join(MetricDefinition, MetricDefinition.id == MetricContract.definition_id)
            .filter(MetricDefinition.metric_id == metric_id)
            .one_or_none()
        )

    def read_on_datasets(self, dataset_ids: Iterable[int]) -> list[MetricContract]:
        dataset_ids = list(dataset_ids)
        if not dataset_ids:
            return []
        return (
            self.query()
            .join(MetricDefinition, MetricDefinition.id == MetricContract.definition_id)
            .filter(MetricDefinition.dataset_id.in_(dataset_ids))
            .all()
        )

    def read_approved(self) -> list[MetricContract]:
        return self.query().filter(MetricContract.status == ReviewStatus.APPROVED.value).all()

    def read_first_approved_on(self, dataset_id: int) -> MetricContract | None:
        return (
            self.query()
            .join(MetricDefinition, MetricDefinition.id == MetricContract.definition_id)
            .filter(MetricDefinition.dataset_id == dataset_id, MetricContract.status == ReviewStatus.APPROVED.value)
            .first()
        )

    def count_on(self, dataset_id: int, *, origin: str, status: ReviewStatus) -> int:
        return (
            self.query()
            .join(MetricDefinition, MetricDefinition.id == MetricContract.definition_id)
            .filter(
                MetricDefinition.dataset_id == dataset_id,
                MetricContract.origin == origin,
                MetricContract.status == status.value,
            )
            .count()
        )

    # -------------------------UPDATE---------------------------
    def update(self, contract: MetricContract, values: dict[str, Any]) -> MetricContract:
        return super().update(contract, values)

    # -------------------------DELETE---------------------------
    def delete(self, contract: MetricContract) -> None:
        super().delete(contract)
