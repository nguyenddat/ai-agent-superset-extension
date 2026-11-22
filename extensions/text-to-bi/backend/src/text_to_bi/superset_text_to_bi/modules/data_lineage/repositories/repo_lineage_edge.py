from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import LineageEdge


class LineageEdgeRepository(BaseRepository[LineageEdge]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, LineageEdge)

    # -------------------------READ---------------------------
    def read_between(self, dataset_ids: Collection[int]) -> list[LineageEdge]:
        if not dataset_ids:
            return []
        return list(self.session.scalars(select(self.model).where(
            self.model.source_dataset_id.in_(dataset_ids), self.model.target_dataset_id.in_(dataset_ids)
        )).all())

    def read_key(self, source_id: int, target_id: int, kind: str) -> LineageEdge | None:
        return self.session.scalar(select(self.model).where(
            self.model.source_dataset_id == source_id,
            self.model.target_dataset_id == target_id,
            self.model.kind == kind,
        ))

    def read_pair(self, source_id: int, target_id: int, kind: str) -> list[LineageEdge]:
        return list(self.session.scalars(select(self.model).where(
            self.model.source_dataset_id.in_((source_id, target_id)),
            self.model.target_dataset_id.in_((source_id, target_id)),
            self.model.kind == kind,
        )).all())
