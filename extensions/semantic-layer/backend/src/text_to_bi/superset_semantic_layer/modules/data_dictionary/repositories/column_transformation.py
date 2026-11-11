from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from ....common.base_repo import BaseRepository
from ..models import ColumnDictionary, ColumnTransformation, ColumnTransformationSource


class ColumnTransformationRepository(BaseRepository[ColumnTransformation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnTransformation)

    def for_columns(self, column_ids: Iterable[int]) -> list[ColumnTransformation]:
        return self.query().filter(ColumnTransformation.column_id.in_(list(column_ids))).all()

    def sources_of(self, column_ids: Iterable[int]) -> list[Any]:
        """(source row, source column) of the transformations of these columns, in their declared order."""
        return self.session.execute(
            select(ColumnTransformationSource, ColumnDictionary)
            .join(ColumnDictionary, ColumnTransformationSource.source_column_id == ColumnDictionary.id)
            .where(ColumnTransformationSource.column_id.in_(list(column_ids)))
            .order_by(ColumnTransformationSource.column_id, ColumnTransformationSource.position)
        ).all()

    def replace_sources(self, column_id: int, source_column_ids: list[int]) -> None:
        """Swap a transformation's input columns for new ones, keeping their order."""
        stored = self.session.scalars(
            select(ColumnTransformationSource).where(ColumnTransformationSource.column_id == column_id)
        ).all()
        for item in stored:
            self.session.delete(item)
        # The unique source constraint must see the old rows gone before the new ones arrive.
        self.flush()
        self.add_all(
            ColumnTransformationSource(column_id=column_id, source_column_id=source_id, position=position)
            for position, source_id in enumerate(source_column_ids)
        )
        self.flush()

    def into_datasets(self, dataset_ids: Iterable[int]) -> list[Any]:
        """(target column, expression, source column) for each declared input of a column of these datasets."""
        target = aliased(ColumnDictionary)
        source = aliased(ColumnDictionary)
        return self.session.execute(
            select(target, ColumnTransformation.expression, source)
            .join(ColumnTransformation, ColumnTransformation.column_id == target.id)
            .join(ColumnTransformationSource, ColumnTransformationSource.column_id == ColumnTransformation.column_id)
            .join(source, ColumnTransformationSource.source_column_id == source.id)
            .where(target.dataset_id.in_(list(dataset_ids)))
            .order_by(target.id, ColumnTransformationSource.position)
        ).all()
