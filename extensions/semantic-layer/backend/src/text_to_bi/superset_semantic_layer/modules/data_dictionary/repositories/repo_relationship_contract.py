from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models import RelationshipContract


class RelationshipContractRepository(BaseRepository[RelationshipContract]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, RelationshipContract)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any]) -> RelationshipContract:
        return self.add(RelationshipContract(**values), flush=False)

    # -------------------------READ---------------------------
    def read(self, contract_id: int) -> RelationshipContract | None:
        return self.get(contract_id)

    def read_by_from_column(self, from_dataset_id: int, from_column: str) -> RelationshipContract | None:
        return (
            self.query()
            .filter(
                RelationshipContract.from_dataset_id == from_dataset_id, RelationshipContract.from_column == from_column
            )
            .one_or_none()
        )

    def read_for_update(self, from_dataset_id: int, from_column: str) -> RelationshipContract | None:
        statement = (
            select(RelationshipContract)
            .where(
                RelationshipContract.from_dataset_id == from_dataset_id, RelationshipContract.from_column == from_column
            )
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def read_approved(self) -> list[RelationshipContract]:
        return self.query().filter(RelationshipContract.status == "approved").all()

    def read_approved_between(self, dataset_ids: Iterable[int]) -> list[RelationshipContract]:
        dataset_ids = list(dataset_ids)
        return (
            self.query()
            .filter(
                RelationshipContract.status == "approved",
                RelationshipContract.from_dataset_id.in_(dataset_ids),
                RelationshipContract.to_dataset_id.in_(dataset_ids),
            )
            .all()
        )
