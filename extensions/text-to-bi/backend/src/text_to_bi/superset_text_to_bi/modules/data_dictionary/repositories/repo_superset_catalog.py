from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SupersetDatabase, SupersetDataset, SupersetDatasetColumn


class SupersetDatabaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def read_by_id(self, database_id: int) -> SupersetDatabase | None:
        return self.session.get(SupersetDatabase, database_id)

    def read_all(self) -> list[SupersetDatabase]:
        statement = select(SupersetDatabase).order_by(SupersetDatabase.database_name)
        return list(self.session.scalars(statement).all())


class SupersetDatasetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def read_by_id(self, dataset_id: int) -> SupersetDataset | None:
        return self.session.get(SupersetDataset, dataset_id)

    def read_by_ids(self, dataset_ids: Collection[int]) -> list[SupersetDataset]:
        if not dataset_ids:
            return []
        statement = select(SupersetDataset).where(SupersetDataset.id.in_(dataset_ids))
        return list(self.session.scalars(statement).all())

    def read_by_database_id(self, database_id: int) -> list[SupersetDataset]:
        statement = (
            select(SupersetDataset)
            .where(SupersetDataset.database_id == database_id)
            .order_by(SupersetDataset.schema, SupersetDataset.table_name, SupersetDataset.id)
        )
        return list(self.session.scalars(statement).all())


class SupersetDatasetColumnRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def read_by_id(self, column_id: int) -> SupersetDatasetColumn | None:
        return self.session.get(SupersetDatasetColumn, column_id)

    def read_by_dataset_id(self, dataset_id: int) -> list[SupersetDatasetColumn]:
        statement = (
            select(SupersetDatasetColumn)
            .where(SupersetDatasetColumn.table_id == dataset_id)
            .order_by(SupersetDatasetColumn.column_name, SupersetDatasetColumn.id)
        )
        return list(self.session.scalars(statement).all())

    def read_by_dataset_and_name(self, dataset_id: int, column_name: str) -> SupersetDatasetColumn | None:
        statement = select(SupersetDatasetColumn).where(
            SupersetDatasetColumn.table_id == dataset_id,
            SupersetDatasetColumn.column_name == column_name,
        )
        return self.session.scalar(statement)
