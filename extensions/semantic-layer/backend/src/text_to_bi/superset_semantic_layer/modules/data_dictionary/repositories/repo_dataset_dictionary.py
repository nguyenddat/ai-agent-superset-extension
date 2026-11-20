from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models import DatasetDictionary


class DatasetDictionaryRepository(BaseRepository[DatasetDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetDictionary)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any]) -> DatasetDictionary:
        return self.add(DatasetDictionary(**values))

    # -------------------------READ---------------------------
    def read(self, dataset_id: int) -> DatasetDictionary | None:
        return self.get(dataset_id)

    def read_all(self) -> list[DatasetDictionary]:
        return self.query().all()

    def read_by_ids(self, dataset_ids: Iterable[int]) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.id.in_(list(dataset_ids))).all()

    def read_by_type(self, dataset_type: str) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.dataset_type == dataset_type).all()

    def read_by_types(self, dataset_types: Iterable[str]) -> list[DatasetDictionary]:
        return self.query().filter(DatasetDictionary.dataset_type.in_(list(dataset_types))).all()

    def read_datasets_of_type(self, database_id: int, dataset_type: str) -> list[Any]:
        return (
            self.session.query(SqlaTable, DatasetDictionary)
            .join(DatasetDictionary, DatasetDictionary.id == SqlaTable.id)
            .filter(SqlaTable.database_id == database_id, DatasetDictionary.dataset_type == dataset_type)
            .all()
        )

    def read_existing_ids(self, dataset_ids: Iterable[int]) -> set[int]:
        statement = select(DatasetDictionary.id).where(DatasetDictionary.id.in_(list(dataset_ids)))
        return set(self.session.scalars(statement))

    def read_classifications(self, dataset_ids: Iterable[int]) -> list[Any]:
        statement = select(DatasetDictionary.id, DatasetDictionary.layer_id, DatasetDictionary.dataset_type).where(
            DatasetDictionary.id.in_(list(dataset_ids))
        )
        return self.session.execute(statement).all()

    def read_pii_flags(self, dataset_ids: Iterable[int]) -> dict[int, bool]:
        statement = select(DatasetDictionary.id, DatasetDictionary.contains_pii).where(
            DatasetDictionary.id.in_(list(dataset_ids))
        )
        return {dataset_id: bool(contains_pii) for dataset_id, contains_pii in self.session.execute(statement).all()}

    # -------------------------UPDATE-------------------------
    def update_clear_layer(self, layer_id: int) -> None:
        self.query().filter(DatasetDictionary.layer_id == layer_id).update(
            {DatasetDictionary.layer_id: None}, synchronize_session=False
        )
