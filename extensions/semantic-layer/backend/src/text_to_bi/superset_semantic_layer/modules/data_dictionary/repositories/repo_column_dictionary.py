from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models import ColumnDictionary


class ColumnDictionaryRepository(BaseRepository[ColumnDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnDictionary)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any]) -> ColumnDictionary:
        return self.add(ColumnDictionary(**values))

    # -------------------------READ---------------------------
    def read(self, column_id: int) -> ColumnDictionary | None:
        return self.get(column_id)

    def read_by_dataset(self, dataset_id: int) -> list[ColumnDictionary]:
        statement = (
            select(ColumnDictionary).where(ColumnDictionary.dataset_id == dataset_id).order_by(ColumnDictionary.id)
        )
        return list(self.session.scalars(statement).all())

    def read_by_datasets(self, dataset_ids: Iterable[int]) -> list[ColumnDictionary]:
        return self.query().filter(ColumnDictionary.dataset_id.in_(list(dataset_ids))).all()

    def read_in_dataset(self, dataset_id: int, column_id: int) -> ColumnDictionary | None:
        return self.query().filter(
            ColumnDictionary.id == column_id, ColumnDictionary.dataset_id == dataset_id
        ).one_or_none()

    def lock_in_dataset(self, dataset_id: int, column_id: int) -> ColumnDictionary | None:
        statement = select(ColumnDictionary).where(
            ColumnDictionary.dataset_id == dataset_id, ColumnDictionary.id == column_id
        ).with_for_update()
        return self.session.scalars(statement).one_or_none()

    def read_by_column_name(self, dataset_id: int, column_name: str) -> ColumnDictionary | None:
        statement = select(ColumnDictionary).where(
            ColumnDictionary.dataset_id == dataset_id, ColumnDictionary.column_name == column_name
        )
        return self.session.scalars(statement).first()

    def read_by_ids(self, column_ids: Iterable[int]) -> list[ColumnDictionary]:
        return self.query().filter(ColumnDictionary.id.in_(list(column_ids))).all()

    def read_primary_keys(self, dataset_id: int) -> list[ColumnDictionary]:
        return self.query().filter(ColumnDictionary.dataset_id == dataset_id, ColumnDictionary.is_pk.is_(True)).all()

    def read_key_columns(self) -> list[ColumnDictionary]:
        return self.query().filter((ColumnDictionary.is_pk.is_(True)) | (ColumnDictionary.is_unique.is_(True))).all()

    def read_referencing(self, column_ids: Iterable[int]) -> list[ColumnDictionary]:
        return self.query().filter(
            ColumnDictionary.referenced_column.in_(list(column_ids)), ColumnDictionary.is_fk.is_(True)
        ).all()

    def read_references(self, dataset_ids: Iterable[int]) -> list[Any]:
        referenced = aliased(ColumnDictionary)
        return self.session.execute(
            select(ColumnDictionary, referenced)
            .join(referenced, ColumnDictionary.referenced_column == referenced.id)
            .where(ColumnDictionary.dataset_id.in_(list(dataset_ids)))
        ).all()

    def read_primary_key_names(self, dataset_ids: Iterable[int]) -> list[Any]:
        statement = select(ColumnDictionary.dataset_id, ColumnDictionary.column_name).where(
            ColumnDictionary.dataset_id.in_(list(dataset_ids)), ColumnDictionary.is_pk.is_(True)
        )
        return self.session.execute(statement).all()
