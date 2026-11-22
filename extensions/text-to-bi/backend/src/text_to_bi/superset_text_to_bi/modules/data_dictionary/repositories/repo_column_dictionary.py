from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import ColumnDictionary


class ColumnDictionaryRepository(BaseRepository[ColumnDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnDictionary)

    # -------------------------READ---------------------------
    def read_by_dataset_id(self, dataset_id: int) -> list[ColumnDictionary]:
        return list(self.session.scalars(select(self.model).where(self.model.dataset_id == dataset_id)).all())

    def read_saved_names(self, dataset_ids: Collection[int]) -> list[tuple[int, str]]:
        if not dataset_ids:
            return []
        statement = select(self.model.dataset_id, self.model.column_name).where(self.model.dataset_id.in_(dataset_ids))
        return [(row.dataset_id, row.column_name) for row in self.session.execute(statement)]

    # (dataset, column, referenced dataset, referenced column) for every saved reference out of the given datasets.
    def read_references(self, dataset_ids: Collection[int]) -> list[tuple[int, str, int, str]]:
        if not dataset_ids:
            return []
        statement = select(
            self.model.dataset_id, self.model.column_name, self.model.referenced_dataset_id,
            self.model.referenced_column_name,
        ).where(
            self.model.dataset_id.in_(dataset_ids), self.model.referenced_dataset_id.is_not(None),
            self.model.referenced_column_name.is_not(None),
        )
        return [tuple(row) for row in self.session.execute(statement)]
