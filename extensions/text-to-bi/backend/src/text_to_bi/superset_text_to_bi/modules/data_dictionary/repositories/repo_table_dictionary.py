from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import TableDictionary


class TableDictionaryRepository(BaseRepository[TableDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TableDictionary)

    # -------------------------READ---------------------------
    def read_by_dataset_id(self, dataset_id: int) -> TableDictionary | None:
        return self.session.scalar(select(self.model).where(self.model.dataset_id == dataset_id))

    def read_by_dataset_ids(self, dataset_ids: Collection[int]) -> list[TableDictionary]:
        if not dataset_ids:
            return []
        return list(self.session.scalars(select(self.model).where(self.model.dataset_id.in_(dataset_ids))).all())

    # -------------------------UPDATE-------------------------
    def clear_catalog_references(self, catalog_id: UUID) -> None:
        statement = update(self.model).where(self.model.indicator_catalog_id == catalog_id).values(
            indicator_catalog_id=None
        )
        self.session.execute(statement, execution_options={"synchronize_session": "fetch"})
