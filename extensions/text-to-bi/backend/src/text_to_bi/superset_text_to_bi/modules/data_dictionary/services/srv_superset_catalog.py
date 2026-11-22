from collections.abc import Collection

from sqlalchemy.orm import Session

from ..models import SupersetDatabase, SupersetDataset, SupersetDatasetColumn
from ..repositories import (
    SupersetDatabaseRepository,
    SupersetDatasetColumnRepository,
    SupersetDatasetRepository,
)


class SupersetCatalogService:
    """Read Superset's canonical database, dataset and dataset-column records."""

    def __init__(self, session: Session) -> None:
        self.database_repository = SupersetDatabaseRepository(session)
        self.dataset_repository = SupersetDatasetRepository(session)
        self.column_repository = SupersetDatasetColumnRepository(session)

    def database(self, database_id: int) -> SupersetDatabase | None:
        return self.database_repository.read_by_id(database_id)

    def databases(self) -> list[SupersetDatabase]:
        return self.database_repository.read_all()

    def dataset(self, dataset_id: int) -> SupersetDataset | None:
        return self.dataset_repository.read_by_id(dataset_id)

    def datasets_by_ids(self, dataset_ids: Collection[int]) -> list[SupersetDataset]:
        return self.dataset_repository.read_by_ids(dataset_ids)

    def datasets_for_database(self, database_id: int) -> list[SupersetDataset]:
        return self.dataset_repository.read_by_database_id(database_id)

    def dataset_columns(self, dataset_id: int) -> list[SupersetDatasetColumn]:
        return self.column_repository.read_by_dataset_id(dataset_id)

    def dataset_column(self, dataset_id: int, column_name: str) -> SupersetDatasetColumn | None:
        return self.column_repository.read_by_dataset_and_name(dataset_id, column_name)
